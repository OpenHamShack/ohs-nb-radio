# OpenHamShack Radio 0.1.17

The update banner shows one line (`ham-0.1.17.txt`); this is the whole
story. Installed copies from 0.1.16 offer this release by themselves.

## ON AIR means on air

- **ON AIR now shows only while you are actually transmitting.** That
  covers the red frame, the ON AIR button and the readout's "on air". Before,
  with FT8 or FT4 Enable TX on, it showed for most of every receive slot
  too, because an over counted as soon as it was queued.
- **Between overs, the button reads ARMED** with "next over in N s".
  Pressing it, or Escape, halts: Enable TX goes off and the waiting over
  is dropped. (Escape did nothing between overs before.)

## A fuller log, for help from a distance

The log now records what someone helping you remotely needs:

- every setting change, with its old and new value;
- each over: what was sent, when against its slot, through which radio and
  sound device, and how it ended;
- the sound device: which one an over opens, why one will not open, and
  any audio underruns;
- a one-line summary of each FT8/FT4 slot;
- where the computer's clock gets its time.

Passwords and tokens are blanked out of the setting lines. **Help › Open
log folder** shows where the log is.

## Ajazz AKP03E control pad

- **Settings › Control pad** shows whether the pad is found and working
  and, if not, why: another program has it (close the Ajazz or Mirabox
  software), no permission, or unplugged.
- **Test controller** lights each key in turn and then lists every key,
  button and knob as you use it. Nothing reaches the radio during the
  test.
- **Copy controller report** gives a short report to email us. From a
  terminal, use `openhamshack-ham --pad-report`.
- **The pad cannot transmit until you allow it.** K1 held is PTT, but it
  shows *PTT off* and keys nothing until **The pad may transmit** is
  ticked and saved. Try the pad with the test first.
- The Windows build now carries what the pad needs, and the Linux .deb
  installs a rule so that your own user can open it.
- No real pad has been used with these programs yet.
