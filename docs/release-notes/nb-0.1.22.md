# OpenHamShack QO-100 NB 0.1.22

The update banner shows one line (`nb-0.1.22.txt`); this is the whole story,
for anyone who wants it. Installed copies from 0.1.16 on offer this release
by themselves - on Linux too, which stayed on 0.1.18 while 0.1.19 to 0.1.21
went out for Windows only, so Linux also gets everything those three
brought (the TX lock and beacon search fixes, reassigning the control
pad's keys, FT8 replies in the right slot, TX = RX, and the pad keep-alive).

## A new window

- **Three workspaces: Digital, Voice and Watch.** Each lays the window out
  for what you are doing: Digital gives the decode list most of the room,
  Voice the scopes and the transmit card, Watch the wide scope and the band
  list. Choosing a mode brings its workspace; the **Workspace** button at
  the end of the tab row picks one yourself. The tab row under the scopes
  no longer moves.
- **Grouped mode buttons**, with a compact form, recent modes, a KG-STV
  button, and **Ctrl + E** for a type-ahead mode menu. The control pad's
  MODE key steps through them in the same order.
- **Fits a small screen.** The window has three sizes of layout (Full,
  Compact and Tight) and works down to 1024 x 600; nothing is cut off at
  any size or in a longer language.
- **Text size** 100, 115 or 130 % in Settings › Display, and every text
  colour is readable against its background.
- **Red only means transmit.** Limits and warnings are amber, text you sent
  is gold, and nothing on the screen is red while you are receiving.
- **The transmit card says it plainly** when this computer cannot transmit
  (no radio able to, `--receive-only`, a setting missing) instead of
  showing controls that do nothing.
- **The S-meter reads "S (beacon ref)"** by default on NB: S-units measured
  from the beacon, since the Pluto is not calibrated in dBm.
- **The scopes label their controls** (an Adjust pill on each), and
  streaming text tags and FT8 labels keep clear of them; FT8 labels for
  calls to you are gold, as their rows are.
- **What is this?** Right-click a signal on either scope to see what it
  probably is, with one click to decode it or listen.
- Screen readers get a name and a state for every control.

## Digital modes

- **Q65 and JS8 get their own panels.** JS8 decodes and sends at all five
  speeds, with CQ, heartbeat, replies, Enable TX and Halt, through the same
  transmit guard as FT8.
- **Band activity**: times, short country names, calls to you in gold, and
  a pile-up line saying who a station is working, who is calling it, and
  where you stand. Halt TX is no longer red when nothing is going out.
- The slot panel fits a small window; Q65 and JS8 tune to their own marks.

## First start

- The Welcome asks your **licence class** beside your callsign, so NB
  knows what you may transmit, and every step has **Skip**.

## Fixes

- The receiver reads the radio ahead of the DSP, so a busy window can no
  longer starve it; playback resumes with the whole jitter buffer; a
  recording says whether the disk or the radio's stream lost samples.
- Auto-tune finds a voice's edge above a leaked carrier rather than on it,
  and when unsure offers its guesses for the next press.
- The beacon lock names an unsteady beacon; the beacon view stamps every
  list in UTC; HTML bulletins are drawn properly.
- Over-power signals (and LEILA's siren) are found and shown where they are.
- Sound devices keep their whole names on Windows.
- Changing theme keeps the waterfalls, band activity and text.
- The pad's record key goes red while recording.

## The name

- OpenHamShack NB is now **OpenHamShack QO-100 NB** everywhere. Windows upgrades
  the installed copy in place (one entry in Apps & features); on Linux the
  `openhamshack-nb` package replaces `openhamshack-nb`. Your settings move across
  at the first start.
