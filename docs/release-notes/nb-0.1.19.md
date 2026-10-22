# OpenHamShack QO-100 NB 0.1.19

The update banner shows one line (`nb-0.1.19.txt`); this is the whole story,
for anyone who wants it. Installed copies from 0.1.16 on offer this release
by themselves.

## For IC-9700 users: TX lock no longer stacks its corrections

0.1.18 taught TX lock to correct the IC-9700's transmit frequency on NB's
own FT8 and FT4 overs. On one station it went wrong: four overs in a row
each measured an error of one to two kilohertz, each was added on top of
the last, and the saved correction reached about 5.4 kHz - which was then
used on air. The radio had taken every change, but the signal TX lock was
measuring did not move with it, and NB never checked that it had.

0.1.19 fixes that:

- **Each correction is worked out from where the radio actually was.** NB
  measures the radio's own error against the frequency the IC-9700
  reported during the over, and sets the correction to that, rather than
  adding each over's error to the last. A correction the radio never
  received can no longer be counted twice.
- **Each correction is checked.** After a correction, the next over must
  show the same error for the radio. If the signal did not move with it,
  NB puts the last correction back, says *TX lock stopped correcting the
  IC-9700*, and corrects nothing more until you switch TX lock off and on
  again.
- **New setting: Largest TX lock correction** (Settings › Transmitter, under
  TX lock; 1000 Hz by default). TX lock never corrects by more than this.
  A larger error is shown, not corrected. A GPS-locked radio and
  upconverter need a few hundred hertz at most.
- **A runaway saved correction is reset at start-up.** If the correction
  NB saved last time is beyond that limit, it is set back to 0 when NB
  starts, so a value like the 5.4 kHz above never goes on air again.
- **It corrects only when the receive side is settled:** beacon lock in
  Auto, locked on a beacon and steady for 30 seconds before you key, and
  not moving during the over. An over in which the radio changed frequency
  corrects nothing, and a receive correction you change by hand means the
  saved transmit correction is no longer trusted.

As before, NB corrects only between overs, never while you transmit, and
only from a CW carrier or its own CAT PTT overs. If you set XIT by hand,
keep it off.

## Beacon lock: a better search

When beacon lock loses the beacon it searches for it. That search had
three faults, found while looking at a station whose LNB had stopped
delivering any signal:

- **The middle beacon's strength was misread** during the search, so the
  checks meant to refuse a weak or wrong signal never applied to it. It is
  now measured properly.
- **Falling back to the lower beacon was too hard.** With the middle
  beacon gone and the lower beacon heard well enough to track, the search
  found it in the right place every second but never locked to it. The
  search now asks the same of a beacon as tracking does, so it falls back
  to the other beacon when the chosen one cannot be heard.
- **It says what it heard.** With nothing on the band, the search used to
  name the Pluto's own spur at the centre of the receiver as if it were a
  station. Now a beacon heard but too weak is reported as such, and
  silence is reported as *no beacon heard within ±N kHz* - which points at
  the dish, LNB or cable rather than at NB.

## The CW decoder no longer makes up Morse

NB shares its CW decoder with OpenHamShack Radio, and this release brings
NB the decoder Radio 0.1.20 has had since 13/10.

- **It waits for a real signal.** It starts printing only once a tone has
  stood clearly over the noise beside it for a couple of seconds, so band
  noise, static crashes and a strong neighbour in a wide filter are no
  longer read as letters, and it never settles on a speed from one or two
  marks.
- NB still turns upside-down keying the right way up, as the QO-100
  beacons need.
- **"Decoder hears N wpm" clears when the signal goes**, so the speed shown
  always belongs to someone sending now. The second display's CW panel
  does the same.
