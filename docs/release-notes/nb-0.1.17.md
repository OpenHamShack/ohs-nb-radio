# OpenHamShack QO-100 NB 0.1.17

The update banner shows one line (`nb-0.1.17.txt`); this is the whole story,
for anyone who wants it. Installed copies from 0.1.16 offer this release by
themselves.

## For IC-9700 users

Everything here came from a real IC-9700 on a real Windows PC. The first
level set on one failed, and these changes are what it showed.

- **The radio's own sound device, found for you.** Every Icom with a USB
  port has a sound device called *USB Audio CODEC*, so a PC with two Icom
  radios has two of them. Before, Find could pick the other radio's. Now it
  picks the one on the same USB hub as the 9700's CI-V port (on Windows and
  Linux), and it also recognises a sound device you have renamed, even
  when Windows cuts the name short. If it cannot tell which is which, it
  picks neither and says so. Then **Which sound device?…** in step 3 keys
  the 9700 briefly into the dummy load once per device and keeps the one
  that makes power. Switch any other radio's VOX off first.
- **Find tries every baud rate.** Some 9700s answer only at one speed
  (19200 on the radio that showed this). Find now asks at the saved rate,
  then at every rate the 9700 offers, then at every address, and fills in
  what it found.
- **The level set now works with real radios.** It used to watch the ALC
  meter, but the 9700's ALC reads with any audio at all, so it gave up at
  once. Now it raises NB's digital audio level step by step from -40 dB,
  watches the power output (Po), and keeps the lowest level that gives
  nearly full power. If the power never rises, it says the audio is not
  reaching the radio (wrong sound device, or DATA MOD), rather than giving
  advice about levels.
- **CAT PTT can be switched on from the setup assistant.** Step 3 used to
  stop with a red message when CAT PTT was off or no digital mode was
  chosen. It now offers **Turn on CAT PTT and save…** (after saying what
  NB will then do with the radio: its own digital overs, never voice) and
  **Choose FT8**.
- **New: IC-9700 diagnostic…** (Settings › Transmitter, beside IC-9700
  setup). It writes a plain-text report to send us when something does
  not work.
  - **Run checks** never transmits. It reads the serial ports, which one
    answers, the radio's settings, how fast it answers, and the sound
    devices.
  - **Run keyed checks…** needs the dummy-load tick, then a second
    confirmation naming the band and power. It sends four short tone
    overs, reads Po and ALC at each level, and times key-up and unkey. It
    changes no setting on the radio. If your PTT delay is under 80 ms it
    suggests 80-100 ms.
  - **Copy report** or **Save report…** gets it out. The report holds no
    callsign, locator or serial number.
  - From a terminal: `openhamshack-nb --rig-diagnostic` (on Windows,
    `openhamshack-nb-console.exe --rig-diagnostic`).

### First use with an IC-9700

1. Put the 9700 into a **dummy load**, with RF POWER where you would use it.
2. **Settings › Transmitter › IC-9700 setup…**, step 1, **Find**. Check the
   port, baud rate and sound device it fills in, then **Save**.
3. Step 2, **Check**. Apply what it proposes, or untick anything you want
   left alone.
4. Step 3. If it offers **Turn on CAT PTT and save…** and **Choose FT8**,
   press them. Tick the dummy load. If you have more than one Icom
   connected, press **Which sound device?…** first. Then press **Set audio
   level**.
5. If any step does not do what you expect, run **IC-9700 diagnostic…**:
   **Run checks**, then **Run keyed checks…** into the dummy load, then
   **Save report…**, and send us the file.

## ON AIR means on air

- **ON AIR now shows only while you are actually transmitting.** That
  covers the red frame, the ON AIR button and the downlink's "on air".
  Before, with FT8 or FT4 Enable TX on, it showed for most of every receive slot
  too, because an over counted as soon as it was queued. With an IC-9700
  keyed by CAT PTT, it now follows the radio's own keyed state.
- **Between overs, the button reads ARMED** with "next over in N s".
  Pressing it, or Escape, halts: Enable TX goes off and the waiting over
  is dropped. (Escape did nothing between overs before.)

## A fuller log, for help from a distance

The log now records what someone helping you remotely needs:

- every setting change, with its old and new value;
- each over: what was sent, when against its slot, through which radio and
  sound device, how it ended, and what NB saw of its own signal;
- the sound device and radio link: which port, baud rate and address,
  why a link dropped, and any audio underruns;
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
  terminal, use `openhamshack-nb --pad-report`.
- **The pad cannot transmit until you allow it.** K1 held is PTT, but it
  shows *PTT off* and keys nothing until **The pad may transmit** is
  ticked and saved. Try the pad with the test first.
- The Windows build now carries what the pad needs, and the Linux .deb
  installs a rule so that your own user can open it.
- No real pad has been used with these programs yet.
