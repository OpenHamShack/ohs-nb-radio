# OpenHamShack Radio 0.1.21

The update banner shows one line (`ham-0.1.21.txt`); this is the whole
story, for anyone who wants it. Installed copies from 0.1.16 onwards offer
this release by themselves.

## A new window

- **Three workspaces: Digital, Voice and Watch.** Each lays the window out
  for what you are doing: Digital gives the decode list most of the room,
  Voice the scopes and the transmit card, Watch the wide scope and CW
  Activity. Choosing a mode brings its workspace; the **Workspace** button
  at the end of the tab row picks one yourself. The tab row under the
  scopes no longer moves.
- **Grouped mode buttons**, with a compact form, recent modes and
  **Ctrl + E** for a type-ahead mode menu. The control pad's MODE key steps
  through them in the same order.
- **Fits a small screen.** Three sizes of layout (Full, Compact and Tight),
  down to 1024 x 600; nothing is cut off at any size or in a longer
  language.
- **Text size** 100, 115 or 130 % in Settings › Display, and every text
  colour is readable against its background.
- **Red only means transmit.** Limits and warnings are amber (the licence
  line too), text you sent is gold, and nothing is red while you receive.
- **The transmit card says it plainly** when this computer cannot transmit
  instead of showing controls that do nothing.
- **The scopes label their controls** (an Adjust pill on each); FT8 labels
  for calls to you are gold.
- Screen readers get a name and a state for every control.

## The CW skimmer: CW Activity

- **CW Activity** (Ctrl + K) decodes every CW signal in the CW segment of
  the band you are in, all at once, whatever you are listening to, with
  spot marks on the scope. A click tunes there; it never transmits. It is
  off until you switch it on, at the top of the view or in Settings ›
  Station, because it takes a share of a processor core.

## Digital modes

- **FT8 replies go in your next slot**, not about 27 s later, auto seq is
  no longer a cycle late, and a late start up to 6 s works as in WSJT-X.
- A **TX = RX** switch, and in FT8/FT4 a bigger band activity list whose
  text Ctrl + the mouse wheel makes larger or smaller.
- **Q65 and JS8 get their own panels**; JS8 decodes and sends at all five
  speeds through the same transmit guard as FT8.
- Band activity shows times, short country names, calls to you in gold and
  a pile-up line.

## First start

- Every step of the Welcome has **Skip**.

## Control pad

- **Reassign every key, button and knob** of the pad.
- The AKP03E's keys no longer flicker (a keep-alive every 10 s), and the
  record key goes red while recording.

## Fixes

- The receiver reads the radio ahead of the DSP, so a busy window can no
  longer starve it; playback resumes with the whole jitter buffer; a
  recording says whether the disk or the radio's stream lost samples.
- AM no longer shows a microphone where AM cannot transmit.
- Sound devices keep their whole names on Windows.
- Changing theme keeps the waterfalls, band activity and text.

## The name

- OpenHamShack HAM is now **OpenHamShack Radio** everywhere. Windows upgrades
  the installed copy in place; on Linux the `openhamshack-radio` package
  replaces `openhamshack-ham`. Your settings move across at the first start.
