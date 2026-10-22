# OpenHamShack QO-100 NB 0.1.18

The update banner shows one line (`nb-0.1.18.txt`); this is the whole story,
for anyone who wants it. Installed copies from 0.1.16 and 0.1.17 offer this
release by themselves.

## For IC-9700 users: TX lock now keeps your transmit frequency right

- **NB corrects the radio's transmit frequency for you on FT8 and FT4
  overs.** When NB keys the IC-9700 by CAT PTT, it now finds its own
  signal in the downlink, measures how far off it landed, and moves the
  radio's transmit frequency between overs to correct it. Usually the
  first over finds it and the second reads **TX LOCKED**. Before, TX lock
  searched but never found the signal, so a radio that landed a few
  hundred hertz off stayed off, over after over.
- **If you set XIT by hand to make up for that offset, switch XIT off.**
  NB's correction and a hand-set XIT would add together and put you off
  frequency again.
- It is careful about what it believes. Each over moves the frequency by
  at most 2 kHz, and only when most of its measurements agree, so one odd
  reading costs one over, not a jump. It never corrects towards a beacon:
  with the dish off, or a dummy load and no signal in the downlink, it
  changes nothing.
- No new setting and no new command to the radio. When you key the radio
  yourself (speech, or WSJT-X through the radio), NB shows roughly where
  you are but corrects nothing, as before.

## Sending KG-STV pictures

NB has received KG-STV pictures in the background for a while. Now it can
send them, through a Pluto or an IC-9700 (by CAT PTT, like the other
digital modes).

- **Beacon › KG-STV › Send picture…** opens a dialog that only prepares.
  Choose a picture, see it as a receiver will paint it, and choose a
  quality. Each quality shows how long its over takes; any longer than
  your transmit time-out cannot be chosen.
- The callsign line is your call and locator from Settings › Station.
  Without a callsign there is no Send.
- Choose where to send: KG-STV's frequency or wherever you are tuned now.
  Nothing keys until **Send**, and the usual band-plan and time-out checks
  apply. The narrow (500 Hz) segment refuses a picture.
- While it goes, a strip above the picture shows the block and the time
  left, with a **Halt** button. Escape halts it too.
- So far it has been proven against NB's own KG-STV receiver, not yet
  against KG-STV's own program or on the air.

## The scopes: an "SDR Console-like" look

If you compare NB with SDR Console, the beacons look relatively higher in
SDR Console. Neither is wrong: NB's zoom scope shows narrow bins, so a
carrier stands at full height and a wide signal like the middle beacon
looks lower. SDR Console averages more widely.

- Each scope's adjust panel (Scope tab) now has a **Display style**:
  **Standard** (today's look, the default) or **SDR Console-like**, which
  uses a wider resolution bandwidth (about 100 Hz) and a short hold and
  fall on the trace. The waterfall follows the same style.
- It changes only what you see. Receive SNR, vs beacon, the level guard
  and beacon lock all work exactly as before.
- **The RBW is now shown** in the frequency axis, after the unit (for
  example "kHz +10489 RBW 18 Hz"), in both styles, so you can tell what
  each bin covers.

## Optional diagnostics upload

When something goes wrong, the most useful thing to send us is the log
from the moment it happened. NB can now send it for you, but only if you
turn it on.

- **Off unless you turn it on:** Settings › Station › Diagnostics, **Send
  diagnostics to OpenHamShack automatically**. The full explanation of
  what is sent is right beside the switch. Turn it off there at any time.
- When on, it sends a report a minute after a fault (an over that failed
  or was stopped, no power out, a lost radio link, a sound card failure,
  a crash), after the IC-9700 diagnostic or level set, and once a day if
  anything new was logged. At most one fault report every 30 minutes.
  Never while transmitting, and never on a connection your computer says
  is metered.
- **Help › Send diagnostics…** sends one now, even with the switch off.
- Each report gets a **reference code** like SHACK-7KQ4, shown in
  Help › Send diagnostics… and written in the log. Quote it when you ask
  for help.
- Reports are deleted after 30 days, and only the people who write
  OpenHamShack read them. The privacy page,
  https://openhamshack.com/privacy/, says what is sent, where it goes and
  how long it is kept.
- Passwords, tokens and **device serial numbers** are removed before
  anything leaves your computer. Serial numbers go wherever they appear:
  the IC-9700's in its port name (on Linux and Windows), an SDRplay's,
  and a Pluto's. Your callsign and locator can be in a report, because
  they are what it is about.

## OpenHamShack Remote, with an OpenHamShack box

When QO-100 NB runs as an app on an OpenHamShack box, each decode it sends
to OpenHamShack Remote now names the station's country, from the same
country file the desktop uses, so Remote and the desktop agree. Each over
you send also appears in Remote's list as your own TX. A box gets this
when its NB app is next updated.
