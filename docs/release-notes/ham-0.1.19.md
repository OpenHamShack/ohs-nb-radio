# OpenHamShack Radio 0.1.19

The update banner shows one line (`ham-0.1.19.txt`); this is the whole
story, for anyone who wants it. Installed copies from 0.1.16 and 0.1.17
offer this release by themselves. (There was no public 0.1.18: a check
on the Windows build found the start-up problem below, and the fix
became 0.1.19.)

## Band buttons

- **The band row shows only the bands your radio can reach**, directly or
  through a converter. An HF-only radio no longer shows a row of dead VHF
  and UHF buttons, and a Pluto no longer shows dead HF ones. A band that
  one Pluto setting would open (its AD9364 setting: 4 m, 2 m, 6 cm) stays
  in the row, faint, and clicking it explains the setting and offers it.
  The row changes when you change radio, converters or that setting.
- **The first visit to a band lands somewhere sensible:**
  - in a digital mode, on that band's FT8 dial (FT4's, if you are in FT4
    and the band has one);
  - otherwise at the start of the band's SSB segment, LSB below 10 MHz and
    USB above (for example 3.603 MHz on 80 m, 7.053 MHz on 40 m,
    14.125 MHz on 20 m), from the band plan you have chosen;
  - from FM, a first visit to 2 m or 70 cm stays in FM on the calling
    channel, 145.500 or 433.500 MHz.
- After the first visit a band comes back as you left it, as before, and
  pressing the button again still offers its other places (FT8, SSB, CW).

## The scopes: an "SDR Console-like" look

- Each scope's adjust panel (Scope tab) now has a **Display style**:
  **Standard** (today's look, the default) or **SDR Console-like**, which
  uses a wider resolution bandwidth (about 100 Hz) and a short hold and
  fall on the trace, closer to what SDR Console shows. The waterfall
  follows the same style. It changes only what you see.
- **The RBW is now shown** in the frequency axis, after the unit, in both
  styles, so you can tell what each bin covers.

## Optional diagnostics upload

When something goes wrong, the most useful thing to send us is the log
from the moment it happened. Radio can now send it for you, but only if
you turn it on.

- **Off unless you turn it on:** Settings › Station › Diagnostics, **Send
  diagnostics to OpenHamShack automatically**. The full explanation of
  what is sent is right beside the switch. Turn it off there at any time.
- When on, it sends a report a minute after a fault (an over that failed
  or was stopped, no power out, a lost radio link, a sound card failure,
  a crash) and once a day if anything new was logged. At most one fault
  report every 30 minutes. Never while transmitting, and never on a
  connection your computer says is metered.
- **Help › Send diagnostics…** sends one now, even with the switch off.
- Each report gets a **reference code** like SHACK-7KQ4, shown in
  Help › Send diagnostics… and written in the log. Quote it when you ask
  for help.
- Reports are deleted after 30 days, and only the people who write
  OpenHamShack read them. The privacy page,
  https://openhamshack.com/privacy/, says what is sent, where it goes and
  how long it is kept.
- Passwords, tokens and **device serial numbers** are removed before
  anything leaves your computer: an SDRplay's, a Pluto's, and a USB serial
  adapter's in its port name (on Linux and Windows). Your callsign and
  locator can be in a report, because they are what it is about.

## OpenHamShack Remote, with an OpenHamShack box

When Radio runs as an app on an OpenHamShack box, each decode it sends to
OpenHamShack Remote now names the station's country, from the same country
file the desktop uses, so Remote and the desktop agree. Each over you send
also appears in Remote's list as your own TX. A box gets this when its
Radio app is next updated.

## Starting from the command line

`--band` together with `--mode` (for example `--band 20m --mode ft8`)
now lands where that mode belongs on the band, the FT8 dial in this
case. With the new first-visit rule, the band was applied first and could
land in the SSB segment instead. `--rf` still sets the exact frequency.
