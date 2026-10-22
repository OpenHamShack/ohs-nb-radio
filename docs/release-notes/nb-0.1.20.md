# OpenHamShack QO-100 NB 0.1.20

The update banner shows one line (`nb-0.1.20.txt`); this is the whole story,
for anyone who wants it. Installed copies from 0.1.16 on offer this release
by themselves.

## Control pad: choose what each key, button and knob does

Until now the control pad (the Ajazz AKP03E) did one fixed set of things.
Now you can change it.

- **Settings › Control pad › Keys and knobs** has a row for each of the six
  keys (K1 to K6), the three small buttons (B1 to B3) and the three knobs
  (D1 to D3) - what a knob does when turned, and when pressed. Pick from
  the list what that control should do in QO-100 NB, or **Nothing**.
- A key can also do one step of a knob's job: *Tune up one step*, *Next
  memory*, *Volume down* and so on.
- The pictures on the keys follow your choices.
- Changes take effect when you press **Save**. **Cancel** leaves the pad as
  it was, and **Reset to defaults** puts back the layout NB ships with
  (listed in the user guide).
- Your choices are kept with the station profile, so they survive updates.

## New things a pad control can do

- **Noise reduction** on and off.
- **Filter width** on a knob: the high edge in SSB, the width in CW and AM.
  The digital modes' filter is fixed, so it does nothing there.
- **Beacon lock: Hold / Auto**, the same as the **H** key.

## Transmitting from the pad is as safe as before

- **PTT stays behind "The pad may transmit".** Until that box in
  Settings › Control pad is ticked and saved, the PTT key shows *PTT off*
  and keys nothing, wherever you put it.
- PTT can go on only one of the six keys with a picture, and only on one:
  choosing it for another key moves it there. Set it to **Nothing** on
  every key and the pad cannot transmit at all; the page says so.
- When it does key, it goes through every check the TX button makes, and
  the transmitter stops at once if the pad is unplugged or NB stops
  answering it.
- While you are transmitting, Save will not move or remove the PTT key, so
  the key you are holding always stops the transmission.
