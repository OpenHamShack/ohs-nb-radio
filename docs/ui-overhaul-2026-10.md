# QO-100 NB and Radio: the UI overhaul of October 2026

A plan, not code. Brian approved the items on 17/10/2026 (A-H below, and
the smaller ones folded in after them). This page says what the window
becomes, splits the work into packages one agent each can build, and ends
with the decisions only Brian can make. Every claim about today's code
names its file; guesses are marked **(guess)**.

Sources read for it: `~/openhamshack/docs/GUIDE.md` (section 3 checklist,
section 5 traps), this repo's `DESIGN.md` ("User interface"),
`docs/USERGUIDE.md` ("The window"), `docs/I18N.md`, the code under
`ohscore/ui/`, `ohsnb/ui/` and `ohsradio/ui/`, and the Mac test of 17/10/2026
(`~/build/mac-nb-test/FINDINGS.md`, screenshots `window-1710.png`,
`ft8.png`, `ft8mode.png`, `q65.png`, `small.png`).

**When:** no package starts until the rename (`feature/nb-rename`,
worktree `~/wt/nb-rename`, no commits yet on 17/10) has merged to `main`.
It changes visible strings and the i18n catalogs every package here also
regenerates. Paths below are as of `main` effd8f6 and keep their names
unless the rename moves a file; re-check them when you pick up a package.

## Contents

1. [Where the window is today](#1-where-the-window-is-today)
2. [The layout: workspaces (A)](#2-the-layout-workspaces-a)
3. [Window sizes: tiers and a real minimum](#3-window-sizes-tiers-and-a-real-minimum)
4. [Mock-ups](#4-mock-ups)
5. [The other approved items (B-H and the small ones)](#5-the-other-approved-items)
6. [Change checklist (GUIDE section 3)](#6-change-checklist-guide-section-3)
7. [Safety rules every package keeps](#7-safety-rules-every-package-keeps)
8. [Work packages](#8-work-packages)
9. [The bug batch from the Mac test: what folds in](#9-the-bug-batch-from-the-mac-test-what-folds-in)
10. [Decisions for Brian](#10-decisions-for-brian)

## 1. Where the window is today

- One window class for both apps, `BaseWindow` in `ohscore/ui/window.py`;
  NB's `MainWindow` (`ohsnb/ui/mainwindow.py`) and Radio's
  (`ohsradio/ui/mainwindow.py`) add their header badges, transmit card, views
  and shortcuts.
- Layout (`window.py` `build()`): header (brand, `Readout`, the app's
  badges, `PttButton`, four `IconButton`s); then three splitters:
  `split_side` = [`split_main`, rail], `split_main` = [wide scope,
  `split_low`], `split_low` = [zoom scope, lower panel]. The rail is a
  scroll area of `ModeGrid`, the transmit card and `ReceiveCard`
  (`ohscore/ui/rail.py`), 290-400 px wide. The status strip is
  `StatusStrip` (`ohscore/ui/chrome.py`).
- There is already a first workspace: `split_kind` "" or "slot"
  (`window.py` `SPLIT_PREFS`, `_use_split_kind`, `default_splitters`).
  FT8 and FT4 get their own splitter sizes (`slotSplitters` in
  `ohscore/ui/prefs.py`), wide scope 30 % of the height, zoom under a
  quarter of the width (Ray, 16/10/2026). Sizes are saved as absolute
  pixels, so they do not carry across window sizes.
- The lower panel's tab row is a `Segmented` of Mode / Logbook / Memories
  plus the app's views (NB: Beacon, Band; Radio: CW Activity), then a
  plain `QLabel` (`panel_title`) with the mode's name: that label is the
  "last tab" titled "USB" or "q65" (`switch_panel`: `MODE_LABELS.get(mode,
  mode)`; Q65 and JS8 are missing from `MODE_LABELS` in `rail.py`).
- Q65 and JS8 fall through `panel_key()` (`ohscore/ui/panels/__init__.py`)
  to the voice panel. The engine has both: Q65-60A decodes and encodes
  (`ohscore/modes/q65.py`), JS8 Normal decodes only, sending waits for
  Brian (`ohscore/modes/js8.py`, `ohscore/modes/__init__.py` `_js8_entry`).
  The simulator sends neither (`ohsnb/devices/sim.py` has no Q65/JS8
  station).
- `setMinimumSize(1180, 700)` (`window.py` line 99). The Mac capture
  `small.png` shows the layout broken (readout digit lost, STEP chip and
  "HSmodem" clipped, "MESSAG", footer overlap, wide waterfall one row).
  **(guess)** The capture is 1600 x 900 and its menu bar is 24 px, which
  matches a 1600 x 900 logical display; the window would then be about
  980 x 600 points, below the 1180 x 700 floor, so either macOS did not
  enforce the minimum for an Accessibility resize, or the floor held and
  the content breaks at 1180 x 700 anyway. WP6 measures both on the Mac.
- Text sizes are pixel sizes in `theme.font(px)` (`ohscore/ui/theme.py`);
  `theme.stylesheet(scale)` already takes a scale that no caller passes
  (`ohsnb/ui/__init__.py`, `ohsradio/ui/__init__.py`). Many widgets fix their
  own pixel heights (`ModeCell` 34, `IconButton` 38, `StatusStrip` 28,
  `SlotRing` 96).
- Small grey text is `text3`: `#667284` on the dark cards `#10141b` is
  3.8:1 (3.5:1 on `bg2`); light theme `#8592a3` on `#eef1f5` is 2.8:1.
  Light `warn` (`#d98a00`) as text on white is 2.8:1, `accent` 3.8:1,
  `ok` 3.3:1. WCAG AA for small text is 4.5:1.

## 2. The layout: workspaces (A)

A **workspace** is a set of proportions and panel forms for one kind of
operating. There are three. The radio, the scopes' own settings, the
views and every control are the same in all three; a workspace only
decides how much room each part gets and how much of each card shows.

### 2.1 What each one is for and shows

| | **Digital** | **Voice** | **Watch** |
|---|---|---|---|
| For | FT8, FT4, Q65, JS8, PSK31/63/125, RTTY; also SSTV, KG-STV, HSmodem (decision 1) | USB, LSB, CW, AM, FreeDV; Radio's FM | looking at the whole band: who is where, what is that signal |
| Comes on | with any of its modes | with any of its modes | only when picked |
| Wide scope + waterfall | 25 % of the body height | 42 % | 66 % |
| Zoom scope | 17 % of the main width, never under 160 px (still wide enough to click RX and TX offsets) | 45 % of the lower width (the biggest it gets) | 22 % of the lower width |
| Lower panel shows | **Operate** (band activity / terminal / pictures) by default | **Operate** (mic and voice keyer; CW decoder and macros; FreeDV status) | **Band** (NB's skimmer and over-the-beacon list) or **CW Activity** (Radio) by default |
| Rail | full width (about 320 px): Mode full, Transmit compact, Receive compact | full width: Mode full, Transmit full, Receive full with the large S-meter | slim (about 210 px): Mode as three group buttons, Receive compact; Transmit hidden while nothing can or does transmit |
| Decode text | 16 px at 100 % (was 15; Ray asked for larger), still Ctrl + wheel | n/a | n/a |

"Compact" Receive is S-meter, SNR, volume and mute, AGC, and a "More
receive controls" line that expands it in place (the rest of
`ReceiveCard` today). "Compact" Transmit is power, the own-signal-vs-beacon
meter and any standing warning; ALC and the level-guard sentence come back
when expanded or on the air. Expanding a card in a workspace is
remembered for that workspace.

### 2.2 Switching

- **Auto (the default):** the workspace follows the mode, Digital for the
  Digital and Pictures groups, Voice for the Voice group
  (`ohscore/modegroups.py`, new, WP0).
- **Picking one** pins it: the **Workspace** button at the right end of
  the tab row (menu: Auto - follows the mode, Digital, Voice, Watch,
  then "Reset this workspace's layout"); View › Workspace with the same
  items; **W** cycles Digital, Voice, Watch (pinning), **Shift + W** goes
  back to Auto. Single letters are the window's habit (`window.py`
  `eventFilter`: f, z, r, x, s, n, m, a; NB's h); w is free.
- **While pinned:** a press of a mode button, a mode key or the pad's
  MODE key brings that mode's workspace and returns to Auto (decision 2:
  a mode button is a request to operate). Tuning from the Band list,
  from "What is this?", from a memory or a scope click changes the mode
  without leaving the pinned workspace, so browsing the band from Watch
  stays in Watch.
- A switch never changes the mode, the frequency, the view's content or
  anything about transmitting. It runs after the mode change it follows,
  never before.
- A switch only resizes and shows or hides widgets that already exist: no
  rebuild, no new widgets. The Mac test saw receive overruns from heavy
  window actions (FINDINGS 10, 29); a switch must cost under 50 ms of the
  GUI thread (measured in WP1's test).

### 2.3 What is kept, and where

New `ui.json` keys (all added by WP0 in `ohscore/ui/prefs.py`):

- `workspace`: "auto", or the pinned "digital" / "voice" / "watch".
- `workspaces`: per workspace, the splitters as **fractions** (wide vs
  lower, zoom vs panel) and the rail width in px, the lower view last
  shown, and which rail cards are expanded. Fractions, so the layout the
  operator dragged at 1920 x 1080 is the same layout in full screen, on
  a 1366 x 768 laptop or after "Larger text".
- `modeRecent`: the last modes used, newest first (for decision 3).
- `textScale`: 1.0, 1.15 or 1.3.
- Migration on first load: `splitters` becomes Voice's fractions and
  `slotSplitters` Digital's, worked out with the saved window geometry.
  The old keys stay (a downgrade still reads them).
- "Reset this workspace's layout" puts that workspace's defaults back.

### 2.4 How it meets the rest of the window

- **Full screen** (F11, View › Full screen): the workspace stays; the
  fractions are applied to the new size; the tier (section 3) is worked
  out again. Nothing enters or leaves full screen by itself.
- **The views** (Logbook, Memories, Beacon, Band, CW Activity) are the
  same in every workspace. Each workspace remembers which was showing; a
  mode-button press shows Operate.
- **Second display** (`ohscore/ui/second.py`): unchanged; it shows the
  wide waterfall or the mode panel as chosen in Settings, whatever the
  main window's workspace.
- **Theme change** (Ctrl + T) rebuilds the window (`window.py`
  `set_theme`); the workspace, its fractions and expanded cards come
  back as they were (FINDINGS 12, which also loses decode history, is the
  bug batch's: section 9).
- **Dialogs** (Settings, Dish alignment, Welcome): unaffected.
- **Radio:** the same three workspaces; its band bar under the header
  (`ohsradio/ui/mainwindow.py` `_under_header`, `ohsradio/ui/widgets.py`
  `BandBar`) stays in all of them; Watch shows CW Activity.

## 3. Window sizes: tiers and a real minimum

The window picks one of three **tiers** from its size divided by the text
scale (`W' = width / textScale`, `H' = height / textScale`), so "Larger
text" moves the window into a smaller tier rather than clipping. The
rules are one pure function (`ohscore/ui/layoutrules.py`, WP0) that the
window and the tests both call.

| Region | **Full** (W' >= 1500 and H' >= 860) | **Compact** (W' >= 1180 and H' >= 700) | **Tight** (down to the minimum) |
|---|---|---|---|
| Header | as today: brand and tagline, readout digits at their full size, badges, TX tile, four icon buttons | brand icon only; readout digits shrink to fit (never lose a digit); icon buttons in one row | one line: readout, the two badges as small pills, TX tile, a "more" button holding second display / Settings / Logbook / shortcuts |
| Rail | workspace's form | 260 px: Mode as three group buttons, Transmit and Receive compact | hidden; **Controls** button on the tab row opens it as a drawer over the right edge; the mode button (current mode, menu by group) sits on the tab row |
| Wide scope | workspace fraction | same | at least 120 px with at least 40 px of waterfall; spectrum gives way first |
| Zoom scope | workspace fraction, >= 160 px | same | 160 px |
| Band activity (slot modes) | all columns | all columns | below 640 px of panel: DT and Freq move into the row's tooltip; country is the short name |
| Status strip | everything | drops MS/s and CPU into the tooltip of the device item | device, overruns (only when not 0), rxCorr, UTC |

**Minimum window: 1024 x 600** at 100 % text (decision 5), times the text
scale, never more than the screen's available size; Settings › Display
offers only the text sizes whose minimum fits the screen and says why
another is greyed. The Tight tier is what makes 1024 x 600 usable: it
fits 1280 x 720 screens (1920 x 1080 at 150 % scaling on Windows, a Pi on
a 720p monitor) and 1366 x 768 at 100 %. **(guess)** A 1366 x 768 laptop
at Windows' 125 % gives about 1093 x 574 usable and will not fit; it
would need 100 % scaling or full screen.

Drawer rules (Tight): it opens over the panels, not over the scopes'
tuning area; **Esc** while keyed or armed always unkeys first and leaves
the drawer alone; Esc with nothing on the air closes it. Space keeps
meaning PTT; the drawer never takes keyboard focus by itself.

## 4. Mock-ups

Character cells are about 16 x 30 px at 1920 x 1080. `[x]` is a button or
chip, `┃` a splitter or card edge, `░▒▓█` waterfall. The colours are
section 5.4's: nothing in these is red while receiving.

### 4.1 Digital at 1920 x 1080 (FT8, Full tier)

```
+----------------------------------------------------------------------------------------------------------------------+
| File  View  Radio  Help                                                                                              |
| (o) OpenHamShack QO-100 NB    DOWNLINK · MHZ                   [RX·BEACON LOCKED +0.5 Hz]  [     TX     ]  [▣][⚙]    |
|     QO-100 narrowband         10 489.540 000                   [TX·OWN SIGNAL  IDLE     ]  [Enable TX below]  [▤][?] |
|                               UP 2400.040 000  RIT XIT SPLIT STEP 500 Hz  ● narrow digimodes (500 Hz max)            |
+-------------------------------------------------------------------------------------------------+--------------------+
| CW |NARROW DIGI|DIGI|  SSB ONLY  |  SSB ONLY  |   MIXED MODES, CONTESTS   |MM  (band-plan strip)| MODE               |
| ◆Lower beacon       IK3ITB          ◆Middle beacon                               Multimedia◆    | VOICE   USB LSB CW |
|  _/\__/\|\__/\___/\_____/\/\___/\________/\_______/\______/\/\____/\______/\_/\___              |         AM FreeDV  |
| kHz +10489  RBW 400 Hz   550      600      650      700      750      800      850      900     | DIGITAL [FT8] FT4  |
| ░░▓░░░░░▓█▓░░░░▓░░░░░▓▓░░░░░░░▓░░░░░░░░▓▓░░░░░░▓░░░░░▓▓░░░░░░▓░░░░░░▓░  [≡ Adjust]              |  Q65 JS8 PSK31 63  |
| ░░▓░░░░░▓█▓░░░░▓░░░░░▓▓░░░░░░░▓░░░░░░░░▓▓░░░░░░▓░░░░░▓▓░░░░░░▓░░░░░░▓░                          |  PSK125 RTTY       |
|        wide scope + waterfall: 25 % of the body height (~225 px)                                | PICTURES SSTV      |
+----------------+--------------------------------------------------------------------------------| KG-STV HSmodem     |
| zoom  -20      | [Operate] Logbook  Memories  Beacon  Band         [Workspace: Digital · auto ▾]| TRANSMIT  (compact)|
| RX1500 ┃       | FT8 · decoder ohsdigi · 15 s slots, next in 6 s                                 | Power  -40.0 dB    |
|  ┃TX1500       | Pile-up: 7P8GE (Ghana) · 7 calling: EA7KP +1, RD7P -6, +5 more · not you       | ▬▬▬▬▬▬▬●───────┃   |
| ▁▂▆█▆▂▁ ┃      | UTC       dB   DT  Freq  Message            Country ┃QSO [Halt TX] [Log] [Clr] | vs beacon  -6 ▮▮   |
| ┃  ┃           | 15:38:45  -6 +0.3  1514  7P8GE RD7P LN23    Russia  ┃DX call [     ] Grid [  ] |                    |
| ░▓░┃░▓░░       | 15:38:45  -4 +0.5  1379  7P8GE R5DT KO94    Russia  ┃ ( 2 )   [Even][Odd]      | RECEIVE  (compact) |
| 7P8GE DL5XL    | 15:38:45  -9 +0.4  1717  7P8GE LZ1GHT KN12  Bulgaria┃ RX EVEN  RX/TX 1500      | S7 (beacon ref)    |
| 7P8GE E70A     | 15:38:45  +1 +0.3  2398  7P8GE EA7KP IM97   Spain   ┃Tx1 —                     | ▬▬▬▬▬▬▬▬▬▬──────   |
| ░▓░┃░▓░░       | 15:38:45  -4 +0.1  1813  7P8GE DD8KO JO30   Germany ┃Tx2 —                     | SNR 18 dB          |
| ░▓░┃░▓░░       | ---- 15:39:00 ------------------------------------- ┃Tx3 —                     | Volume ──●──── [M] |
| (17 % of the   | 15:39:00  +4 +0.4  2162  EA1EAU S9R RR73    São Tomé┃Tx4 —                     | AGC  Off Fast[Med] |
|  width, 270 px:| 15:39:00 +13 +0.3  1658  CQ II4JOTA         Italy   ┃Tx5 —                     | ▸ More receive     |
|  wide enough   | ... ~20 rows at 16 px (Ray: more room, bigger text) ┃Tx6 CQ GM4BRI IO75        |                    |
|  to click RX   |                                                     ┃Enable TX [ ] Auto seq[x] |                    |
|  and TX offsets|                                                     ┃TX = RX   [ ] Hold TX [x] |                    |
|                |                                                                                |                    |
|                |                                                                                |                    |
|                |                                                                                |                    |
|                | ■ CQ  ■ to you  ✓ worked before · click a line to answer it                    |                    |
|                |                                                                                |                    |
|                |                                                                                |                    |
+----------------------------------------------------------------------------------------------------------------------+
| ● Pluto  1.2 MS/s  CPU 3 %  overruns 0  rxCorr +31031.6 Hz  txCorr +0.0 Hz (+0.000 ppm)             15:40:45 UTC     |
+----------------------------------------------------------------------------------------------------------------------+
```

The wide scope still carries the FT8 call labels on its waterfall and the
skimmer's marks; the zoom is tall and narrow, which suits FT8's labels.
The pile-up line (H) sits above the band activity. The rail's Mode card
shows all three groups; Transmit and Receive are compact.

### 4.2 Voice at 1920 x 1080 (USB, Full tier)

```
+----------------------------------------------------------------------------------------------------------------------+
| File  View  Radio  Help                                                                                              |
| (o) OpenHamShack QO-100 NB    DOWNLINK · MHZ                   [RX·BEACON LOCKED +0.5 Hz]  [     TX     ]  [▣][⚙]    |
|     QO-100 narrowband         10 489.540 000                   [TX·OWN SIGNAL  IDLE     ]  [ TX  Space   ]  [▤][?]   |
|                               UP 2400.040 000  RIT XIT SPLIT STEP 500 Hz  ● narrow digimodes (500 Hz max)            |
+-------------------------------------------------------------------------------------------------+--------------------+
| CW |NARROW DIGI|DIGI|  SSB ONLY  |  SSB ONLY  |   MIXED MODES, CONTESTS   |MM  (band-plan strip)| MODE               |
| ◆Lower beacon                     ◆Middle beacon                               Multimedia◆      | VOICE  [USB] LSB CW|
|  _/\__/\|\__/\___/\___/^^\_/\/\___/\___/^^^\__/\______/\/\____/\______/\_/\___                  |        AM FreeDV   |
|                 SSB?        SSB         SSB?             (skimmer marks)                        | DIGITAL FT8 FT4 Q65|
| kHz +10489  RBW 400 Hz   550      600      650      700      750      800      850      900     |  JS8 PSK31 63 125  |
| ░░▓░░░░░▓░░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░░▓▓░░░░░░▓░░░░░░▓░  [≡ Adjust]                  |  RTTY              |
| ░░▓░░░░░▓░░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░░▓▓░░░░░░▓░░░░░░▓░                              | PICTURES SSTV      |
| ░░▓░░░░░▓░░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░░▓▓░░░░░░▓░░░░░░▓░                              |  KG-STV HSmodem    |
| ░░▓░░░░░▓░░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░░▓▓░░░░░░▓░░░░░░▓░                              |                    |
| ░░▓░░░░░▓░░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░░▓▓░░░░░░▓░░░░░░▓░                              | TRANSMIT           |
| ░░▓░░░░░▓░░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░░▓▓░░░░░░▓░░░░░░▓░                              | Power  -40.0 dB    |
|        wide scope + waterfall: 42 % of the body height (~380 px)                                | ▬▬▬▬▬▬▬●───────┃   |
+--------------------------------------------+----------------------------------------------------+ ALC ▮▮▮▮──────     |
|  zoom scope: 45 % of the lower width       | [Operate] Logbook Memories Beacon Band  [Voice·auto| VS BEACON          |
|              -20                           | USB · voice                                        | -30  -20  -6 ┃0 +10|
|      ┃▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒┃       -30      | MICROPHONE                                         | Level guard: 6 dB  |
|   ___┃/\/\/^^\/\/\/\/^\/\┃___   -40        | Mic gain ────●──── +0 dB   Compressor ──●── 6 dB   |  under the beacon  |
|      ┃  passband 300-2700 ┃                | MIC LEVEL  ▮▮▮▮▮▮──────────────────────            | RECEIVE  (full)    |
|  kHz +10489  RBW 18 Hz   625    626    627 | Monitor [ ]   Monitor level ──●── 30 %             | S9 (beacon ref)    |
|  ░░░░┃░▓▒▓▓▒▓▒▓▓▒▒▓▓▒▒▓░░░┃░░░             |                                                    | ▬▬▬▬▬▬▬▬▬▬▬▬▬▬──   |
|  ░░░░┃░▓▒▓▓▒▓▒▓▓▒▒▓▓▒▒▓░░░┃░░░  [≡ Adjust] | VOICE KEYER                                        | SNR in passband 18 |
|  ░░░░┃░▓▒▓▓▒▓▒▓▓▒▒▓▓▒▒▓░░░┃░░░             | [F1 CQ] [F2] [F3] [F4] [F5] [F6]      Edit…        | Volume ──●── [Mute]|
|  ░░░░┃░▓▒▓▓▒▓▒▓▓▒▒▓▓▒▒▓░░░┃░░░             | Repeat [ ] every 10 s                              | AGC Off Fast [Med] |
|  ░░░░┃░▓▒▓▓▒▓▒▓▓▒▒▓▓▒▒▓░░░┃░░░             |                                                    | Gain (AGC off) +0  |
|  ░░░░┃░▓▒▓▓▒▓▒▓▓▒▒▓▓▒▒▓░░░┃░░░             | (CW here: the decoder's text and the               | Filter 300 ── 2700 |
|  ░░░░┃░▓▒▓▓▒▓▒▓▓▒▒▓▓▒▒▓░░░┃░░░             |  macro row; FreeDV: sync, SNR, text)               | NB [ ]   NR [x]    |
|  ░░░░┃░▓▒▓▓▒▓▒▓▓▒▒▓▓▒▒▓░░░┃░░░             |                                                    | NR strength 100 %  |
|  ░░░░┃░▓▒▓▓▒▓▒▓▓▒▒▓▓▒▒▓░░░┃░░░             |                                                    | [Auto-tune][Best   |
|                                            |                                                    |  audio]  note wraps|
+----------------------------------------------------------------------------------------------------------------------+
| ● Pluto  1.2 MS/s  CPU 3 %  overruns 0  rxCorr +31031.6 Hz  txCorr +0.0 Hz (+0.000 ppm)             15:40:45 UTC     |
+----------------------------------------------------------------------------------------------------------------------+
```

Zoom and Receive get the room. The S-meter reads against the beacon (S9 =
the middle beacon, section 5.11). In CW the same layout carries the
decoder's text and the macro row; in FreeDV its status.

### 4.3 Watch at 1920 x 1080 (picked, Full tier)

```
+----------------------------------------------------------------------------------------------------------------------+
| File  View  Radio  Help                                                                                              |
| (o) OpenHamShack QO-100 NB    DOWNLINK · MHZ                   [RX·BEACON LOCKED +0.5 Hz]  [     TX     ]  [▣][⚙]    |
|     QO-100 narrowband         10 489.540 000                   [TX·OWN SIGNAL  IDLE     ]  [ TX  Space   ]  [▤][?]   |
|                               UP 2400.040 000  RIT XIT SPLIT STEP 500 Hz  ● narrow digimodes (500 Hz max)            |
+--------------------------------------------------------------------------------------------------------+-------------+
| CW |NARROW DIGI|DIGI|   SSB ONLY    |   SSB ONLY    |    MIXED MODES, CONTESTS     |MM  (strip)        | MODE        |
| ◆Lower beacon                         ◆Middle beacon                                       Multimedia◆ | [USB ▾]  Voi|
|                                                                    ┌ +4 dB over beacon ┐               | [FT8 ▾]  Dig|
|  _/\__/\|\__/\___/\___/^^\_/\/\___/\___/^^^\__/\______/\/\___/^^^^^\____/\______/\_/\___               | [SSTV ▾] Pic|
|  Data  FT8×12 Data KG-STV  SSB?   SSB  Middle beacon  SSB?  SSB   ...   AMSAT-DL   MM beacon           |             |
| kHz +10489  RBW 400 Hz   550       600       650       700       750       800       850       900     | RECEIVE     |
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░  [≡ Adjust]                  | S9 (bcn ref)|
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              | ▬▬▬▬▬▬▬▬─   |
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              | Vol ─●─ [M] |
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              |             |
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              | (Transmit   |
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              |  card hidden|
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              |  comes back |
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              |  when on air|
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              |  or a warn- |
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              |  ing stands)|
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              |             |
| ░░▓░░░░░▓█▓░░░░▓░░░░▒▒▒▒░░░▓░░░░░░▒▒▒▒░░░░░░▓░░░░▓▓▓▓▓░░░░░▓░░░░░░▓░░░░░░                              | slim rail   |
|        wide scope + waterfall: 66 % of the body height (~600 px), all but the slim rail                | ~210 px     |
|                                                                                                        |             |
+----------------------+---------------------------------------------------------------------------------+-------------+
| zoom 22 %            | Operate Logbook Memories Beacon [Band]             [Workspace: Watch (chosen) ▾]|             |
|    ┃▒▒▒▒▒▒▒┃         | Over the beacon: 10489.812 300  +4 dB over beacon  now   (click to tune)        |             |
| __/\/^^\/\/\__       | 23 signals · 4 SSB dials measured · 34 looks/min · CPU 3.3 % of a core          |             |
| ░░┃░▓▒▓▓▒▓┃░         | Frequency       Signal               Mode Heard SNR Note                        |             |
| ░░┃░▓▒▓▓▒▓┃░         | 10489.540 000   FT8 ×12              FT8  now   18  12 signals: 7P8GE EA1EAU …  |             |
| ░░┃░▓▒▓▓▒▓┃░         | 10489.624 900   KG-STV picture       USB  now   14  DH1BM                       |             |
| ░░┃░▓▒▓▓▒▓┃░         | 10489.747 750   Middle beacon (400 Bd BPSK)  now  14                            |             |
+----------------------------------------------------------------------------------------------------------------------+
| ● Pluto  1.2 MS/s  CPU 3 %  overruns 0  rxCorr +31031.6 Hz  txCorr +0.0 Hz (+0.000 ppm)             15:40:45 UTC     |
+----------------------------------------------------------------------------------------------------------------------+
```

Two thirds of the height is the transponder. The Band list is a short
strip under it; the over-the-beacon row, when there is one, is above the
list. The slim rail keeps what a listener touches: the mode (one button
per group, showing that group's last mode, decision 3), the S-meter and
volume. The transmit card is gone until something transmits or a warning
stands (section 7).

### 4.4 Digital at 1024 x 600 (Tight tier)

```
+--------------------------------------------------------------------------+
| File View Radio Help                                                     |
| 10 489.540 000  UP 2400.040 000 STEP 500 [RX LOCKED][TX IDLE] [ TX ] [⋯] |
+--------------------------------------------------------------------------+
| CW|NARR|DIGI| SSB ONLY | SSB ONLY |  MIXED  |MM                          |
| _/\_/\|\_/\__/\_/\/\__/\___/\_____/\/\__/\_____/\_/\__                   |
| +10489 RBW 400 Hz  600    700    800    900  [≡]                         |
| ░░▓░░░▓█▓░░▓░░░▓▓░░░░▓░░░░░▓▓░░░░▓░░░░░▓░░░░▓░░                          |
| ░░▓░░░▓█▓░░▓░░░▓▓░░░░▓░░░░░▓▓░░░░▓░░░░░▓░░░░▓░░  wide ≥ 120 px           |
+------------+-------------------------------------------------------------+
| zoom       | [Operate] Log Mem Beacon Band  [FT8 ▾] [Controls] [Digital▾]|
| ┃RX ┃TX    | Pile-up 7P8GE · 7 calling · you: not calling                |
| ▁▆█▆▁      | UTC       dB  Message             Ctry  ┃QSO [Halt][Log]    |
| ░▓┃░▓      | 15:38:45  -6  7P8GE RD7P LN23     Russia┃DX [     ]         |
| ░▓┃░▓      | 15:38:45  -4  7P8GE R5DT KO94     Russia┃(2) Even[Odd]      |
| ░▓┃░▓      | 15:38:45  -9  7P8GE LZ1GHT KN12   Bulg. ┃Tx1..Tx6           |
| 160 px     | 15:38:45  +1  7P8GE EA7KP IM97    Spain ┃(scrolls)          |
| min        | 15:39:00 +13  CQ II4JOTA          Italy ┃Enable TX [ ]      |
|            | ... ~11 rows; DT and Freq in the      ┃Auto seq [x]         |
|            |     tooltip (hidden below 640 px)     ┃                     |
|            |                                                             |
|            |                                                             |
+--------------------------------------------------------------------------+
| ● Pluto  overruns 0  rxCorr +31031.6 Hz                   15:40:45 UTC   |
+--------------------------------------------------------------------------+
```

The rail is behind **Controls**; the mode and the workspace are buttons
on the tab row; the band activity drops DT and Freq (in each row's
tooltip); the QSO card keeps Halt TX, the DX call and Enable TX in view
and scrolls the Tx rows. Voice at this size: wide scope 120 px, zoom and
the voice panel share the rest, S-meter and volume on the tab row's
Controls drawer.

## 5. The other approved items

### 5.1 Grouped mode buttons (B)

Groups, defined once in `ohscore/modegroups.py` (no Qt, so the store
form's pad code can use it too):

| Group | QO-100 NB | Radio |
|---|---|---|
| Voice | USB, LSB, CW, AM, FreeDV | USB, LSB, CW, AM, FM, FreeDV |
| Digital | FT8, FT4, Q65, JS8, PSK31, PSK63, PSK125, RTTY | FT8, FT4, JS8, PSK31, PSK63, PSK125, RTTY |
| Pictures & data | SSTV, KG-STV, HSmodem | SSTV |

- **Full form** (rail in Full tier): a small heading per group, the
  group's buttons in a fixed order under it, the current group's heading
  in the accent colour. Fixed positions keep muscle memory (decision 3).
- **Compact form** (Watch, Compact and Tight tiers): one split button per
  group showing that group's **most recent** mode; a click selects it, the
  arrow opens the group's menu. That is "recent first" where room is
  short.
- **Keyboard:** Ctrl + 1 ... 0 stay as they are (`ohsnb/ui/mainwindow.py`
  `MODE_KEYS`, Radio's own); **Ctrl + E** opens the mode menu with
  type-ahead, so Q65, JS8, PSK63/125 and HSmodem have a key path at last
  (FINDINGS 13). The shortcut list says so.
- **Pad:** the MODE key (`mode:next`, `ohscore/padactions.py`) cycles in
  group order instead of today's state-list order. It is shared with the
  store form, which has no window prefs, so it does not use recency.
- **KG-STV** is not a rail mode today: it is received in the background
  and sent as an "over mode" from Beacon › KG-STV (`ohsnb/kgstvrx.py`,
  `ohsnb/ui/kgstvsend.py`, `Engine.OVER_MODES`). Its button opens Beacon ›
  KG-STV and, when nothing is on the air, tunes the receiver to
  10489.6249 USB (decision 4). It does not create a rail mode: changing
  the rail mode unkeys an outgoing picture (`ohscore/engine.py` around
  line 673), and a button that looks like a mode must not do that while
  a picture is going out.

**What Q65 and JS8 need** (both currently show the microphone panel:
FINDINGS 21):

- **Q65 (NB only):** the slot panel, generalised from FT8/FT4
  (`ohscore/ui/panels/ft8.py`: `SLOT`, `late_until`, `SlotRing`, the
  sequencer) to a 60 s period (`ohscore/engine.py` `SLOT_SEC`, `SLOT_LEAD`,
  `SLOT_LATE`). Same message set and QSO card; the ring shows 60 s; the
  header says "Q65-60A · 60 s periods"; the zoom's RX/TX marks are 108 Hz
  wide (Q65-60A's occupied bandwidth, `ohscore/modes/q65.py`); click-to-tune
  rounds as FT8 does (`ohscore/ui/tuning.py`). Labels on the waterfall as
  FT8's, anchored mid-period. Averaging is not offered (not implemented,
  `q65.py`).
- **JS8 (both apps, receive only):** its own panel,
  `ohscore/ui/panels/js8.py`: a band activity like FT8's (UTC, dB, DT,
  Freq, From, Text) where a message's frames (`first`/`last`, `kind`,
  `call`, `to` in each event, `ohscore/modes/js8.py`) are joined into one
  row per message; a filter for "to me" and heartbeats; no Tx rows, no
  Enable TX; one line saying JS8 is receive only in this version. RX mark
  50 Hz on the zoom, no TX mark.
- **Simulator:** a Q65 and a JS8 station in the sim so both panels can be
  seen and tested with no dish (ohsdigi encodes both; the sim never
  radiates, `Device.radiates`).

### 5.2 A fixed tab row (C)

Tabs: **Operate · Logbook · Memories** then the app's own (NB: Beacon,
Band; Radio: CW Activity), in today's order so Ctrl + J / L / B / M / K
keep their places. "Operate" replaces "Mode" (decision 6: "Mode" is also
the rail card's name). The free-standing mode label after the tabs goes.
The mode's name and its one-line status move inside the Operate panel as
its first line ("FT8 · decoder ohsdigi · next slot in 6 s",
"Q65-60A · 60 s periods", "JS8 Normal · receive only", or, in the warning
colour, what a mode is missing, today's `info["missing"]`). The
Workspace button sits at the right end of the row; in Tight the mode
button and Controls join it.

### 5.3 Red only for transmit and danger (D)

Rule: **red (`tx`, `txGlow`, `err`) means on the air, about to be on the
air (armed), over the beacon with our own signal, LEILA, or an error.**
Everything else uses a neutral, accent or amber token. Where a control is
red because it transmits, it is neutral until it actually does.

| Where | Today | Becomes | Package |
|---|---|---|---|
| S-meter beyond S9 / above 0 dB vs beacon: arc band, ticks, bar, the reading (`ohscore/ui/smeter.py` `scale_for` zones `"err"`, digital colour around line 880) | red at any time ("S9+53" in red, window-1710.png) | neutral (`text`, the bar in `rx`); the over-zone turns red only while on the air, when the passband holds our own downlink | WP5 |
| Halt TX in the QSO card (`panels/ft8.py` line 288, `kind="danger"`) | solid red always | neutral button with a stop glyph; red while armed or keyed; hidden when transmit is impossible this run (5.9) | WP4 |
| TX tile (`ohscore/ui/status.py` `PttButton.paintEvent`) | red-tinted fill and red outline whenever available | neutral outline and text when idle; red outline when armed; red fill on the air (unchanged) | WP5 |
| Tx rows in the QSO card (`panels/ft8.py` lines 127-132) | the current row outlined and tinted red when idle ("CQ NOCALL", small.png) | accent outline when chosen; red while that over is armed or on the air | WP4 |
| Our own over in band activity (`panels/ft8.py` line 677) and the terminal's sent text (`panels/common.py` line 84) | red | the `own` gold (the colour that already means "our signal", `theme.py`) | WP4, WP5 |
| Power slider (`ohsnb/ui/rail.py` `colour="tx"`, `ohsradio/ui/rail.py`) and its ceiling mark (`ohscore/ui/controls.py` lines 308-311, `ohscore/ui/meters.py` line 153) | red fill, red mark | accent fill; the ceiling mark amber, tooltip reworded ("the amber mark is the ceiling") | WP5 |
| XIT chip (`ohscore/ui/readout.py` line 253) | red when on | accent, as RIT | WP5 |
| TX audio offset flag and line on the zoom, TX flag and dashed line on the wide scope (`ohscore/ui/scope.py` `mode_flags`, `_paint_mode_marks`, `_paint_tx`) | red at all times | `own` gold dashed while idle; red while on the air | WP7 |
| "To you" rows and labels (`panels/ft8.py` line 514, `window.py` `label_event`, token `mine` #ff8fa3) | pink-red | gold (decision 8) | WP0 (token), WP4 |
| REC in the status strip (`ohscore/ui/chrome.py` line 52) and the pad's REC key (`padactions.py` `faces`, tone "onair") | red | amber with a filled dot (decision 7) | WP1, WP2 |
| Radio's NO LICENCE / NO CLASS / NO TX HERE (`ohsradio/ui/widgets.py` lines 343-352) and "no licence class: TX locked" (`ohsradio/ui/mainwindow.py` line 111) | red | amber: a setting to make, not a fault | WP5 |
| IC-9700 line on the transmit card while the radio transmits, and its "aimed where NB would not" warning (`ohsnb/ui/rail.py`) | red | unchanged (on the air; danger) | - |
| Lock badge "lost", status dot stopped with an error, simulator-fallback badge, error toasts, mic/ALC clipping zones | red | unchanged (errors) | - |
| Over-the-beacon alerts on the wide scope (`ohsnb/ui/opview.py` line 112) | LEILA red, another station over the beacon amber | unchanged (decision 9) | - |
| Waterfall palettes, band-plan segment colours | data, not state | unchanged | - |

Every package that paints adds to one test (`tests/test_ui_colours.py`,
created by WP5): with the simulator receiving and nothing armed, grab each
listed widget and assert no pixel is within a small distance of the
theme's `tx` or `err` colour; then key the simulator and assert the TX
tile, readout and S-meter do turn red. A test that runs the paint, not
one that reads source.

### 5.4 Contrast and a text-size setting (E)

- **Contrast** (WP0, `ohscore/ui/theme.py`): every token used for text
  reaches 4.5:1 on `bg0`, `bg1` and `bg2` in both themes. Starting points
  computed from today's values: dark `text3` `#667284` -> about `#8590a1`
  (5.3:1 on `bg2`); light `text3` `#8592a3` -> about `#5f6b7c` (4.8:1 on
  `bg0`); light `warn`, `ok`, `accent`, `err` darkened for text (or a
  `*Text` variant where the fill must stay bright). A test computes the
  ratios from the theme dicts, so a later colour edit cannot slip under.
  The scope's colours (`SCOPE_KEYS`) are on a dark background in both
  themes and are checked against `scope`.
- **Text size** (WP0): Settings › Display › Text size: 100 %, 115 %,
  130 % (decision 11). `theme.font()` multiplies by it, `theme.px(n)`
  scales a fixed size, `theme.stylesheet(scale)` gets it; it applies at
  once through the same rebuild as a theme change. Fixed pixel sizes are
  converted to `theme.px()` by whichever package owns their file (section
  8), each checking its own widgets at 130 %. The FT8 list's own size
  (`ft8FontPx`, Ctrl + wheel) multiplies with it.

### 5.5 Label the scope controls (F)

The only control drawn on a scope is the "adjust" button in the top-right
corner of each waterfall (`ohscore/ui/scope.py` `_levels_button`,
`_paint_levels_button`), three slider glyphs with a hover tooltip. It
becomes a pill with the glyph and the word **Adjust** (glyph only in
Tight), its tooltip names the scope ("Adjust the band scope: scale,
peaks, waterfall levels and palette" / "...the zoom scope..."), and the
popover (`ohscore/ui/wfpanel.py`) is titled with the scope's name. The
header's icon buttons keep their tooltips; in Full tier they get a
one-word caption under each icon if it fits (WP6 decides by measuring).

### 5.6 "What is this?" on a signal (G)

A **right-click** on either scope opens a small card instead of today's
bare menu (`window.py` `scope_menu`, NB's `scope_menu_items`). Left-click
still tunes, as everywhere. The card:

```
 ┌ What is this? ─────────────────────────────────────┐
 │ FT8 calling window · 12 signals                    │
 │ 10489.540 000 USB · heard now · SNR 18 dB          │
 │ 7P8GE EA1EAU II4JOTA DL5XL …                       │
 │ Narrow digimodes segment (500 Hz max)              │
 │ [ Decode FT8 ]   [ Listen ]                        │
 ├────────────────────────────────────────────────────┤
 │ Lock to this as the lower beacon                   │
 │ Auto-tune onto the voice here        (USB, LSB)    │
 └────────────────────────────────────────────────────┘
```

Identification comes from the band skimmer's latest list (`SkimStore`,
`ohsnb/ui/skimview.py`; entries from `ohsnb/dsp/skim.py` `entries()`): the
entry whose `lo..hi` holds the click (nearest within 300 Hz), with its
label, mode, SNR, heard time, note and measured dial; plus the band-plan
segment (`Face.segment_at`). The mapping is a pure function in a new
`ohsnb/whatis.py`, tested without Qt:

| Skimmer entry | Card says | One-click action |
|---|---|---|
| calling window (`kind` "digital": FT8, FT4/FT8 contest, Q65, JS8) | label, count, the calls heard | **Decode FT8** (or FT4, Q65, JS8): that mode at the window's dial (`skim_tune`), which brings Digital |
| lower / upper beacon (CW) | "Lower beacon (CW)" | **Decode CW**: CW on the beacon with the F1A pitch rule (GUIDE section 5) |
| middle beacon (400 Bd BPSK) | label | **Show its text**: Beacon › Middle beacon (decoded in the background) |
| multimedia beacon (HSmodem) | label | **Show the beacon**: Beacon › Bulletins |
| KG-STV picture (`KNOWN`) | label, sender if heard | **Show pictures**: Beacon › KG-STV |
| AMSAT-DL broadcast | label | **Listen** (USB) |
| SSB, dial measured | "SSB, dial measured" | **Listen**: USB on the measured dial |
| SSB, not measured | "SSB? (dial not measured yet)" | **Listen and auto-tune** (today's skim_tune path) |
| CW | "CW" | **Decode CW** |
| data / data (narrow), not identified | "Data, not identified", width | **Listen**; a "Try as..." submenu (PSK31, RTTY) marked as a try |
| one of the unidentified `KNOWN` signals | its label and "not decoded by OpenHamShack QO-100 NB" | **Listen** |
| carrier, or a signal not looked at yet | "Unmodulated carrier" / "Not looked at yet: the skimmer listens in turn (N looks a minute)" | **Listen** |
| nothing there / skimmer off | the segment, and "Band skimmer off: Settings › LNB & locks" when it is | (the existing items only) |

Every action tunes the receiver only. While on the air or armed the
actions are greyed with "Not while transmitting" (section 7). Radio:
the same card can later read CW Activity's spots; not in this plan.

### 5.7 The pile-up line (H)

One line above the band activity in FT8, FT4 and Q65 (Digital
workspace), from a pure module `ohscore/pileup.py` (no Qt, tested on
synthetic decodes):

- **Who:** the station in the QSO card's DX call if one is set, else the
  station with the most distinct callers in the last two slots of the same
  parity (at least two), with its short country.
- **Callers:** how many, the strongest few with their SNR, "+N more".
- **You:** "not calling", "calling" (our last over went to them), "heard
  here" when our own call comes back through the satellite among the
  callers (NB hears its own downlink), "answered you" when their message
  names us, or "working DL5XL" when they answered someone else.
- Hidden when there is no pile-up; a click on the line puts the station
  in the DX call box (no transmit).

### 5.8 First-run setup and Skip

Welcome (`ohscore/ui/welcome.py`, `ohsnb/ui/welcome.py`,
`ohsradio/ui/welcome.py`) asks callsign, locator **and licence class** on its
first page for NB as Radio already does (`ohsradio/ui/welcome.py`
`class_choices`, moved to `ohscore`). Every page gets **Skip**: it closes,
marks the Welcome seen, keeps the simulator and leaves the licence
unacknowledged, so transmit stays locked (FINDINGS 18).

### 5.9 Transmit UI when transmit is impossible

A new pure classifier (`ohscore/ui/txstate.py`, WP0) reads the bridge
state and says one of: **ok**; **here** (refused at this frequency or
mode now: the band plan, the segment, a beacon: today's
`Bridge.can_key()` sentences); **setup** (no licence acknowledgement or
class with a real radio: Settings can fix it); **never** (this run cannot
transmit: `--receive-only` with `RECEIVE_ONLY_REFUSAL`,
`ohscore/config.py`; a receive-only device, `canTx` false).

- **never / setup:** the Transmit card collapses to one line ("Receive
  only this run" / "Set up to transmit: Settings › Station" with a
  button), the QSO card's Halt TX hides, the TX tile reads "Receive only"
  or "Set up to transmit" with the lock glyph, the pad's HALT TX face is
  dimmed (tone "disabled") but **still halts**.
- **here:** everything stays; the tile says why in a few words ("Not in
  this segment") and the tooltip has the sentence.
- **Never collapsed over a warning:** while anything is on the air
  (`Face.on_air`, which covers an IC-9700 keyed at its own microphone) or
  a standing warning is up (`txWarning`, the IC-9700 "aimed where NB
  would not" line), the card is shown in full whatever the classifier
  says. FINDINGS 4 (the card telling a receive-only run that "nothing is
  refused") is fixed by the same rule.

**TX tile wording** (FINDINGS 14, 25; `PttButton.caption`): ON AIR with
the timer; ARMED with "next over in N s"; otherwise TX over one short
line saying how this mode transmits: "Space to talk" (voice), "Enable TX
below" (FT8, FT4, Q65), "Type, Enter sends" (PSK, RTTY, CW keyboard),
"Send from the panel" (SSTV, HSmodem), "Receive only" (JS8, AM, and the
"never" runs), "Set up to transmit", or the short "here" reason. Sentence
case, not capitals.

### 5.10 Smaller items, and where they land

| Item | Change | Package |
|---|---|---|
| Status-bar timings to diagnostics | the "frame / wide paint / line" text leaves the strip (`window.py` `on_tick` sets `status.extra`); it goes into the CPU item's tooltip and the Save diagnostics report (`ohscore/ui/diagnostics.py`) | WP1 |
| Decode list times | `153845` -> `15:38:45` (`panels/ft8.py` lines 520, 676; JS8's list the same) | WP4 |
| Short country names | "Fed. Rep. of Germany" -> "Germany", "European Russia" -> "Russia" ...: a table (`ohscore/data/dxcc-short.json`) beside cty.dat's names, used by `ohscore/dxcc.py`; the full name stays in the tooltip. Remote names countries from its own cty.dat (GUIDE section 5): the table is the one to share when Remote's NB kind comes | WP4 |
| Waterfall label overlap | `scope.py` `_paint_decodes`: a label that would run past the right edge flips left of its signal; stacked labels give up rather than overlap or run off the bottom; on the zoom, when crowded, the call only; never under the Adjust pill | WP7 |
| Wrap long notes | the Receive card's auto-tune sentence wraps in full form and is one line plus tooltip in compact (`rail.py`, FINDINGS 6); the Band list's Note column wraps to two lines then elides with the full note in the tooltip (`skimview.py`) | WP1, WP7 |
| S-meter "S (beacon ref)" | a new unit: S = 9 + (passband dB - beacon dB) / 6, so the middle beacon reads S9 with no calibration; AGC cannot move it because both levels come from the same receive IQ **(guess: WP5 confirms where `beaconLevel` and the passband level are measured)**; added to `UNITS` in `ohscore/ui/smeter.py` and Settings › Radio; NB's default for new installs (decision 10) | WP5 |

## 6. Change checklist (GUIDE section 3)

1. **Contract:** no contract document changes. The pad's faces use tones
   that exist ("disabled", "warn"); the pad's MODE order is the app's own
   business. The skimmer feed and `api/events` are unchanged.
2. **Server:** none of the window code runs in the store form. Two shared
   pieces do: `ohscore/padactions.py` (MODE order, HALT dimmed, REC tone)
   and the new `ohscore/modegroups.py` and `ohscore/pileup.py` (no Qt).
   The store form's pad gets the same faces; `tests/test_pad.py` covers it.
3. **Fake:** n/a (the fakeboxes are WB's). The NB simulator gains Q65 and
   JS8 stations (WP3).
4. **Android (phone, tablet, TV):** n/a now; Remote's NB kind is planned,
   not built. Two pieces are written to be shared then: the short-country
   table and the pile-up rules (both data/pure).
5. **Apple:** n/a now, as Android.
6. **Desktop:** this is the desktop. Both apps share `ohscore/ui`, so every
   package checks Radio's window as well as NB's (Radio: FM in Voice, no
   Q65, JS8 panel shared, band bar under the header, CW Activity in
   Watch). No pinned engine commit to refresh.
7. **Hardware:** no new device access. Performance: workspace switches
   and tier changes must not cost receive overruns (FINDINGS 10, 29):
   WP1 measures the GUI-thread cost; WP9 records IQ on the Mac while
   switching and checks the overrun count.
8. **Transmit:** nothing new keys anything. The rules in section 7 keep
   halting and the on-air cues intact. No package keys a real radio; all
   transmit tests run on the simulator.
9. **Release:** NB and Radio desktop builds; the NB session cuts both.
   Brian wants one larger NB release (Windows) once this and the bug batch
   are in, with the update-feed fallback merged first, and asks to be
   asked before publishing. These packages only merge to `main`.

## 7. Safety rules every package keeps

1. **Halting never gets harder.** Esc, the TX tile while armed, Halt TX
   while anything is armed or keyed, and the pad's HALT TX keep working
   in every workspace and tier, with any drawer open. Hiding Halt TX is
   allowed only when the classifier says this run cannot transmit at all.
2. **On-air cues never get weaker.** Red frame, ON AIR, the red readout,
   the red TX band on the scopes are unchanged; the colour work only
   removes red from things that are not on the air.
3. **Nothing hidden over a warning.** A collapsed or hidden Transmit card
   comes back in full while on the air (including an IC-9700 keyed by
   hand) or while a standing warning is up.
4. **Layout never transmits.** Workspace switches, tier changes, the
   Welcome's Skip and "What is this?" never key, arm, or change transmit
   settings. "What is this?" tunes the receiver only and is greyed while
   on the air or armed. Skip never acknowledges the licence.
5. **KG-STV stays an over mode.** Its button never changes the rail mode
   while a picture is going out.
6. **No rebuilds on a switch.** Switching only resizes and shows/hides
   (receive overruns, FINDINGS 10).

## 8. Work packages

Ten packages in five phases. Within a phase the packages own disjoint
files and run in parallel (at most three at once, GUIDE section 8);
a phase starts when the one before has merged. A file may belong to
different packages in different phases.

| Phase | Packages (parallel) | Starts after |
|---|---|---|
| 0 | WP0 Foundations | the rename merges |
| 1 | WP1 Workspaces · WP3 Q65 and JS8 · WP5 Transmit state, colours, S-meter | WP0 |
| 2 | WP2 Mode card · WP4 Decode list and pile-up · WP6 Window tiers and minimum | phase 1 |
| 3 | WP7 Scopes and "What is this?" · WP8 First-run setup | phase 2 (WP8 could run earlier: it shares no file) |
| 4 | WP9 Integration, docs, screenshots, Mac and Windows | phase 3 |

### Rules for every package

- Own worktree and branch: `git -C ~/openhamshack-nb worktree add ~/wt/ui-wpN
  -b feature/ui-wpN main` (made by the parent, who passes the path). Land
  with `~/openhamshack/tools/beta-build/merge.sh openhamshack-nb
  feature/ui-wpN` (fast-forward, push to `hub`, worktree and branches
  removed). Commit as you go, one concern each, with the attribution
  lines the parent gives.
- Touch only the files listed as yours. Anything else you need: say so in
  the report; do not edit it.
- **Generated files** are everyone's and no one's: the i18n catalogs
  (`ohscore/i18n/ohscore_en.ts/.qm`, `ohsnb/i18n/ohsnb_en.ts/.qm`,
  `ohsradio/i18n/ohsradio_en.ts/.qm`, the `.pot` files) and
  `i18n-pending.txt`. Regenerate them in your last commit with
  `tools/i18n.py extract`, `pot` and `baseline` (`docs/I18N.md`); on a
  rebase take `main`'s copies and regenerate, never hand-merge.
- **Docs and `docs/screenshots/`** belong to WP9 alone. Packages say in
  their report what the user guide must now say.
- **Screenshots** for acceptance go to `~/build/ui-shots/wpN/`, never the
  default (`ohsnb/ui/screenshots.py` writes into `docs/screenshots` when
  given no folder). Use WP0's matrix (below); look at every picture you
  name in your report.
- Tests: behaviour, offscreen (`QT_QPA_PLATFORM=offscreen python3 -m
  unittest tests.test_x`), only the ones for what you changed plus
  `tests/test_i18n.py` and `tests/test_ui_window.py`. The full suite runs
  once, in WP9. No sub-agents, no sleep loops.
- New tests go in the package's own new files. In an existing test file
  (`tests/test_ui_window.py` above all) change only the test functions
  your change breaks; two packages of a phase never need the same
  function, so git merges the hunks; on a rebase conflict keep both
  sides' intent.
- Check Radio too: `python3 -m ohsradio.ui.screenshots` has the same matrix.
- Every widget you touch is checked at 130 % text and in both themes.

### WP0 Foundations (phase 0, one agent, medium)

The shared pieces the others build on, with no visible change except
contrast.

- **Files:** `ohscore/ui/theme.py` (contrast tokens; `toYou`, `rec`,
  `limit` tokens; `set_scale`, scaled `font()`, `px()`,
  `stylesheet(scale)`); `ohscore/ui/prefs.py` (every new key of section
  2.3, the migration); new `ohscore/modegroups.py` (groups, labels,
  workspace per mode, per-slot-mode spec: period, tone width, transmit
  or not, all as data; `MODE_LABELS` moves here); new
  `ohscore/ui/txstate.py`; new `ohscore/ui/layoutrules.py` (tiers, minimum
  size); `ohscore/ui/rail.py` (move `ModeGrid`, `ModeCell` out, verbatim,
  re-exported); new `ohscore/ui/modegrid.py` (the moved code plus a
  working stub `ModeMenuButton`: current mode, flat menu; WP2 makes it
  grouped); `ohscore/ui/scope.py`, `ohscore/ui/window.py`,
  `ohscore/ui/tuning.py`, `ohscore/ui/panels/__init__.py` (replace the
  `("ft8", "ft4")` literals and the 50/83 Hz widths with modegroups
  lookups, no behaviour change); `ohscore/ui/settings.py` (Display: Text
  size); `ohsnb/ui/__init__.py`, `ohsradio/ui/__init__.py` (apply the scale
  at start); `ohsnb/ui/screenshots.py`, `ohsradio/ui/screenshots.py` (the
  matrix); new `tests/test_ui_foundations.py`.
- **Screenshot matrix:** `python3 -m ohsnb.ui.screenshots OUT --matrix
  modes=usb,ft8,q65,js8,sstv sizes=1920x1080,1366x768,1280x720,1024x600
  scales=1,1.3 themes=dark,light [--workspace watch] [--receive-only]
  [--locale en-XA]` writing `m-<mode>-<WxH>-<scale>-<theme>[-<workspace>].png`.
  It waits long enough for each mode's decodes (two Q65 periods). Every
  later package's screenshot checks use it.
- **Acceptance:**
  - `test_ui_foundations`: contrast of every text token >= 4.5:1 on
    `bg0`/`bg1`/`bg2`, both themes, computed from the dicts; `set_scale(1.3)`
    makes `font(10)` 13 px and `px(34)` 44; a `ui.json` with old
    `splitters`/`slotSplitters` loads as Voice/Digital fractions that
    reproduce the old sizes at the saved geometry within 2 px; every mode
    of `ohsnb.state.MODES` and `ohsradio.state.MODES` is in exactly one group;
    `txstate` gives ok (simulator), never (`--receive-only`; a SoapySDR),
    setup (Pluto, licence not acknowledged), here (a refused segment);
    `layoutrules` tier table cases, including scale.
  - `tests/test_ui_window.py` passes unchanged except the FT8 splitter
    test, rewritten for fractions.
  - Screenshots `m-usb-1920x1080-1-dark` and `m-ft8-1920x1080-1-dark`
    look as before except brighter grey text; `-light` likewise.
  - Settings › Display › Text size 130 % survives a restart.

### WP1 Workspaces, the tab row, timings (phase 1, one agent, large)

- **Files:** `ohscore/ui/window.py`; new `ohscore/ui/workspace.py` (the
  model: state, fractions, defaults per workspace, switching rules);
  `ohscore/ui/rail.py` (`ReceiveCard` compact/full, note wrapping);
  `ohscore/ui/chrome.py` (`StatusStrip`: timings out, tooltip, REC amber);
  `ohscore/ui/diagnostics.py` (timings in the report); new
  `tests/test_ui_workspace.py`.
- **Builds:** section 2 entire, section 5.2, the status-strip and
  Receive-card rows of 5.10. Calls `ModeGrid.set_form()` (stub from WP0)
  per workspace. The Transmit card's compact form is WP5's; WP1 asks it
  through a `set_form()` it calls if present.
- **Acceptance:**
  - Mode usb -> ft8 brings Digital, ft8 -> sstv stays Digital, ft8 -> usb
    brings Voice; W pins Watch; a Band-list tune to an FT8 window keeps
    Watch; a mode-button press leaves Watch for the mode's workspace and
    Auto; Shift + W returns to Auto.
  - Fractions per workspace survive restart, a resize 1920x1080 -> 1366x768
    (within 2 %), full screen and Ctrl + T.
  - A switch adds no QObject to the window and takes under 50 ms including
    `processEvents()` (offscreen, ohs-dev).
  - Each workspace remembers its view; Watch opens on Band (NB) and CW
    Activity (Radio).
  - The tab row's labels are the same in every mode (no "q65"); the
    Operate panel's first line names the mode, in the warning colour for
    a missing piece.
  - Esc unkeys a keyed simulator from each workspace; Watch shows the
    Transmit card in full while keyed and while a `txWarning` stands.
  - The status strip shows no "frame ... ms"; the CPU item's tooltip and
    the saved diagnostics report do.
  - Screenshots: matrix usb and ft8 at 1920x1080 and 1366x768, plus
    `--workspace watch`, both themes; proportions match section 4 within
    5 %; nothing clipped at 130 %.

### WP3 Q65 and JS8 panels (phase 1, one agent, medium-large)

- **Files:** `ohscore/ui/panels/ft8.py` (generalise to any slot mode from
  modegroups); new `ohscore/ui/panels/js8.py`;
  `ohscore/ui/panels/__init__.py`; `ohscore/modegroups.py` (Q65 and JS8
  rows); `ohscore/ui/panels/voice.py` (AM: the receive half only, no
  microphone or keyer: FINDINGS 26); `ohsnb/devices/sim.py` plus a new
  `ohsnb/devices/digisim.py` (a Q65 and a JS8 station); new
  `tests/test_ui_q65_js8.py`.
- **Builds:** section 5.1's Q65 and JS8 parts.
- **Acceptance:**
  - Q65: the slot panel with a 60 s ring; injected Q65 events (as the FT8
    tests inject) fill the band activity; clicking one sets the DX call;
    the sequencer queues an over for the next 60 s period (simulator).
    End to end on the simulator: the sim's Q65 station decodes within two
    periods.
  - JS8: three frames of one message (`first`/`last`) make one row; a
    heartbeat shows as one; no Tx rows or Enable TX exist; the panel says
    receive only; the sim's JS8 station decodes.
  - Zoom: RX and TX marks for Q65 (108 Hz), RX only for JS8; waterfall
    labels for both; click-to-tune rounds like FT8.
  - AM shows no microphone controls.
  - Radio: JS8 shows the JS8 panel.
  - Screenshots: matrix q65 and js8 at 1920x1080 and 1366x768, both
    themes; the ring, the decodes, the marks visible.

### WP5 Transmit state, colours, S-meter (phase 1, one agent, medium-large)

- **Files:** `ohscore/ui/status.py` (`PttButton` wording and colours);
  `ohscore/ui/controls.py` (slider ceiling mark); `ohscore/ui/meters.py`;
  `ohscore/ui/smeter.py` (neutral zones; "S (beacon ref)");
  `ohscore/ui/readout.py` (XIT chip colour only);
  `ohscore/ui/panels/common.py` (sent-text colour); `ohsnb/ui/rail.py`
  (Transmit card: collapse by `txstate`, compact form, colours);
  `ohsradio/ui/rail.py`; `ohsradio/ui/widgets.py` (licence chips amber);
  `ohsradio/ui/mainwindow.py` (status item colour only);
  `ohsnb/ui/face.py` (default S-meter unit, decision 10); new
  `tests/test_ui_colours.py`, `tests/test_ui_txstate.py`.
- **Builds:** sections 5.3 (its rows), 5.9 (all but Halt TX and the pad),
  5.10's S-meter row.
- **Acceptance:**
  - `--receive-only`: the Transmit card is one line, the tile reads
    "Receive only" with the lock; a Pluto config with no licence
    acknowledgement: "Set up to transmit" and a button to Settings; the
    simulator: available. FT8 tile "Enable TX below", USB "Space to talk",
    PSK "Type, Enter sends", SSTV "Send from the panel", JS8 "Receive
    only".
  - With the emulated IC-9700 (`ohscore/rig/civsim.py`) keyed by hand and the licence
    not acknowledged: the card is shown in full with the warning.
  - `test_ui_colours`: no red pixels in the S-meter at S9+40, the idle
    tile, the power slider, the XIT chip, sent text, Radio's licence
    chips; red in the tile, readout and S-meter's over-zone once the
    simulator is keyed.
  - "S (beacon ref)": with the beacon at -60 dBFS and the passband at
    -60 / -72 / -40 dBFS the meter reads S9 / S7 / S9+20; it does not
    move when the AGC setting changes (simulator).
  - Screenshots: matrix usb, ft8 with `--receive-only`, both themes; the
    existing `transmitting-landed-1920` shot still red where it should be.

### WP2 Mode card (phase 2, one agent, medium)

- **Files:** `ohscore/ui/modegrid.py`; `ohsnb/ui/mainwindow.py` (mode
  keys, Ctrl + E, the KG-STV button's action);
  `ohsradio/ui/mainwindow.py`; `ohsnb/ui/chrome.py`, `ohsradio/ui/chrome.py`
  (shortcut lists, including W and Shift + W from WP1);
  `ohscore/padactions.py` (MODE order, HALT dimmed, REC tone);
  `ohscore/ui/padlink.py` (desktop face overrides for "setup"); new
  `tests/test_ui_modegrid.py`.
- **Builds:** section 5.1 except Q65/JS8 panels; the pad rows of 5.3 and
  5.9.
- **Acceptance:**
  - Full form: three headed groups, each app's modes once, fixed order;
    compact form: one split button per group showing its last mode
    (`modeRecent`), its menu lists the group.
  - Every mode reachable by keyboard; Ctrl + E menu with type-ahead;
    `test_every_menu_shortcut_is_in_the_shortcuts_overlay` passes with
    the new rows.
  - KG-STV button: shows Beacon › KG-STV and tunes 10489.6249 USB; while
    the simulator sends a KG-STV picture it only shows the page and the
    picture keeps going.
  - Pad: MODE cycles in group order; with `canTx` false HALT's face is
    "disabled" and a press still calls `halt()`; REC is amber;
    `tests/test_pad.py` passes (store form too).
  - Screenshots: rail at 1920x1080 (full) and 1280x720 (compact), both
    themes, `--locale en-XA`: no clipped labels.

### WP4 Decode list and pile-up (phase 2, one agent, medium)

- **Files:** `ohscore/ui/panels/ft8.py`; `ohscore/ui/panels/js8.py`; new
  `ohscore/pileup.py`; `ohscore/dxcc.py` (short names); new
  `ohscore/data/dxcc-short.json`; new `tests/test_pileup.py`,
  `tests/test_ui_decodes.py`.
- **Builds:** section 5.7; 5.10's times and country names; 5.3's Halt TX,
  Tx rows, own-over and "to you" rows; 5.9's Halt TX hiding; the Tight
  column rule of section 3; decode text default 16 px.
- **Acceptance:**
  - `test_pileup`: target by DX call, by most callers, none with one
    caller; "calling", "heard here", "answered you", "working X".
  - Times read `15:38:45`; "Fed. Rep. of Germany" shows "Germany" with the
    full name in the tooltip; every long name in the bundled cty.dat
    (over 14 characters) has a short form.
  - Halt TX: hidden under `--receive-only`, neutral when idle, red when
    armed (Enable TX on, simulator) and keyed; still halts in each.
  - Below 640 px of panel width the DT and Freq columns hide and the row
    tooltip carries them.
  - Screenshots: matrix ft8 at 1920x1080 and 1024x600, both themes, 1 and
    1.3: the pile-up line, the times, nothing clipped.

### WP6 Window tiers and the minimum (phase 2, one agent, large)

- **Files:** `ohscore/ui/window.py`; `ohscore/ui/workspace.py`;
  `ohscore/ui/readout.py` (digits fit their room; FINDINGS 27, typed
  frequency left in edit mode, folded in); `ohscore/ui/status.py`
  (`PttButton` sizes per tier); `ohscore/ui/chrome.py` (strip per tier,
  `IconButton` sizes, header "more" button); `ohscore/ui/rail.py` (drawer
  form); `ohsnb/ui/status.py` (badges as pills); `ohsradio/ui/widgets.py`
  (`BandBar` fits 1024 px); new `tests/test_ui_tiers.py`.
- **Builds:** section 3 entire; header captions of 5.5 if they fit.
- **Acceptance:**
  - `minimumSize()` is 1024x600 at 100 %, scaled at 115/130 % and capped
    to the screen; the Text size choices that would not fit are greyed.
  - At 1024x600, 1280x720, 1366x768 and 1920x1080, scales 1 and 1.3, both
    apps: no child widget smaller than its `minimumSizeHint()`; the
    readout draws every digit inside its rect; mode labels fit; the band
    activity's Message header is whole; status items do not overlap; the
    wide waterfall is at least 40 px.
  - The Controls drawer opens and closes; Esc while keyed unkeys and
    leaves it open; Esc idle closes it.
  - Tier changes add no QObject and take under 50 ms.
  - On the Mac (verifier, receive-only, no keying): an Accessibility resize
    to 1000x640 stops at the minimum; screenshots at the minimum and full
    screen via `SHACK_DESKTOP_SNAPSHOT` (GUIDE section 5).
  - Screenshots: the whole matrix for usb and ft8, plus `--locale en-XA`
    at 1024x600.

### WP7 Scopes and "What is this?" (phase 3, one agent, medium-large)

- **Files:** `ohscore/ui/scope.py` (Adjust pill, label layout, idle TX
  marks gold, the right-click signal); `ohscore/ui/wfpanel.py` (popover
  title); new `ohsnb/whatis.py`; new `ohsnb/ui/whatis.py` (the card);
  `ohsnb/ui/mainwindow.py` (open the card from `scope_menu`, reuse
  `skim_tune`, `lock_beacon_here`, `auto_tune_at`); `ohsnb/ui/skimview.py`
  (notes wrap); new `tests/test_whatis.py`, `tests/test_ui_whatis.py`.
- **Builds:** sections 5.5, 5.6, 5.10's label-overlap and Band-note rows,
  and 5.3's scope rows.
- **Acceptance:**
  - `test_whatis`: each row of 5.6's table from a synthetic skimmer entry
    gives its title and action; nothing there gives the segment; skimmer
    off says so.
  - Right-click on the simulator's FT8 window opens the card; Decode FT8
    sets FT8 at 10489.540 and brings Digital; on the middle beacon Show
    its text opens Beacon › Middle beacon; while the simulator is keyed
    every action is greyed and nothing retunes.
  - Labels: 30 synthetic FT8 labels on a 270 px zoom never overlap, never
    cross the right edge, never cover the Adjust pill.
  - The Adjust pill reads "Adjust" (glyph only in Tight); its tooltip and
    the popover name the scope.
  - Idle TX marks are gold, red once keyed (`test_ui_colours` gains the
    scopes).
  - Screenshots: the card open over the FT8 window and over the middle
    beacon; the zoom with crowded labels; both themes.

### WP8 First-run setup (phase 3, one agent, small)

- **Files:** `ohscore/ui/welcome.py`; `ohsnb/ui/welcome.py`;
  `ohsradio/ui/welcome.py`; new `tests/test_ui_welcome.py`.
- **Builds:** section 5.8.
- **Acceptance:** Skip on every page, leaving `welcomed` true,
  `licenceAck` false, the device unchanged; NB's first page offers the
  licence classes of the callsign's country (none, with Radio's sentence,
  where no licence is written); a class and the acknowledgement with a
  Pluto config give `txstate` ok. Screenshots of the three pages, both
  apps, both themes, 1024x600.

### WP9 Integration, docs, screenshots (phase 4, one agent, medium)

- **Files:** `docs/USERGUIDE.md` ("The window" rewritten around
  workspaces; the S-meter; FT8/Q65/JS8; the band skimmer's "What is
  this?"; keyboard shortcuts; the first start; "A screen at least
  1024 x 600"), `docs/ham/` user guide likewise, `DESIGN.md` "User
  interface", `docs/screenshots/` (regenerated), `HANDOVER.md`, and
  GUIDE section 5 in `~/openhamshack` for any trap the packages met.
- **Acceptance:** the full suite green on ohs-dev; `tools/i18n.py check`
  clean; `SHACK_LOCALE=en-XA` at 1024x600 shows no clipping in either app;
  `ohsnb.ui.uibench --size 1920x1080` frame cost within 10 % of before WP0;
  Windows and macOS installers built and proved with
  `tools/beta-build/desktop-remote.sh` (receive only), screenshots
  attached; on the Mac a 10-minute IQ recording while switching
  workspaces 20 times shows no more overruns than one without switching.

## 9. The bug batch from the Mac test: what folds in

Brian approved fixing FINDINGS 9-30 as a batch. Some of them are these
packages' work or touch their files, so two agents would collide:

| Finding | Goes to |
|---|---|
| 4, 14, 25 (TX card and tile wording under receive-only) | WP5 |
| 6 (auto-tune note cut off) | WP1 |
| 9 (layout breaks when small) | WP6 |
| 13 (shortcuts sheet clipped; modes without a key) | WP2 (sheet text at 130 % and en-XA too) |
| 18 (Welcome has no Skip) | WP8 |
| 21 (Q65 and JS8 have no panel) | WP3 |
| 26 (AM shows the voice panel) | WP3 |
| 27 (typed frequency stays in edit mode) | WP6 |
| 7 and "fade unsure SSB?" labels (band-list wording) | the bug batch, landing before phase 3 (WP7 owns `skimview.py` then) |
| 12 (theme toggle loses history and the menu label) | the bug batch, landing before phase 1 (it edits `window.py` `set_theme`/`build`) |
| 10, 29 (overruns on window actions) | the bug batch, before phase 1 if it touches `window.py`; WP1/WP6/WP9 measure the result |
| 11, 15, 16, 17, 19, 22, 23, 24, 28 and the recording-drop label | the bug batch, independent of these files |

## 10. Decisions for Brian

**Answered 17/10/2026:** Brian accepted every recommendation below, with REC
**amber** (item 7) on the pad and in the status bar. The pad's REC key is red
on main today (8b0cca5); the package that owns the pad changes it to amber.

Each with the recommendation the plan assumes. Answers that differ change
only the packages named.

1. **Pictures & data modes (SSTV, KG-STV, HSmodem) use the Digital
   workspace** rather than a fourth. *Recommended: yes.* (WP0, WP1)
2. **A mode-button press leaves a workspace you picked by hand** (Watch,
   say) for that mode's workspace; tuning from the Band list, "What is
   this?" or a memory does not. *Recommended: yes.* (WP1)
3. **"Recent first" as fixed buttons plus recency where room is short:**
   the full grid keeps fixed positions; the compact group buttons show
   each group's last mode and the Ctrl + E menu lists recent modes first.
   *Recommended: this,* rather than buttons that reorder themselves.
   (WP2)
4. **The KG-STV button opens Beacon › KG-STV and tunes 10489.6249 USB,**
   and is not a rail mode. *Recommended: yes.* (WP2)
5. **Minimum window 1024 x 600** (today 1180 x 700, which still breaks).
   *Recommended: 1024 x 600.* 1366 x 768 laptops at 125 % scaling stay
   out of reach. (WP0, WP6)
6. **The first tab is named "Operate"** (today "Mode", which is also the
   rail card's name). *Recommended: Operate.* (WP1)
7. **REC is amber, not red,** in the status strip and on the pad, so red
   is only ever transmit. *Recommended: amber.* (WP1, WP2)
8. **Messages to you are gold, not WSJT-X's pink-red.** *Recommended:
   gold.* (WP0, WP4)
9. **Red means our own signal over the beacon, and LEILA;** another
   station over the beacon stays amber. *Recommended: yes.* (none: it is
   today's behaviour)
10. **"S (beacon ref)" is NB's default S-meter unit for new installs;** a
    choice already made is kept. *Recommended: yes.* (WP5)
11. **Text size steps 100 / 115 / 130 %, and the FT8 list's default goes
    from 15 to 16 px.** *Recommended: yes.* (WP0, WP4)
