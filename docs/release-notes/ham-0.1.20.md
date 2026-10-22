# OpenHamShack Radio 0.1.20

The update banner shows one line (`ham-0.1.20.txt`); this is the whole
story, for anyone who wants it. Installed copies from 0.1.16 onwards offer
this release by themselves. This release is about the CW decoder only.

## The CW decoder no longer makes up Morse

Before this release, Radio's CW strip could fill with letters when nobody
was sending: band noise, static crashes, or a station a few hundred hertz
away in a wide filter were read as Morse, with a speed to match.

- **It now waits for a real signal.** The decoder only starts printing
  when a tone has stood clearly over the noise beside it for a couple of
  seconds, and it judges the noise from the quieter side of the tone, so
  a busy neighbour or a strong station nearby does not fool it. Static
  crashes and key clicks are recognised as clicks rather than as dots.
- **It never settles on a speed from one or two marks**, so a single
  crash or carrier no longer starts a run of letters.
- **Radio never reads keying "inside out".** The decoder shared with
  OpenHamShack QO-100 NB can turn upside-down keying the right way up,
  which the QO-100 beacons need. On the terrestrial bands nothing is sent
  that way, and a fading beacon could trigger it for the next station,
  so Radio switches it off.
- Measured on recordings of the real bands from 80 m to 12 m, the
  characters printed from quiet stretches of band fell from about four a
  minute to almost none, and beside a strong station in a 1500 Hz filter
  from about 26 a minute to none. Real stations decode as well as
  before, a little better on the beacons.

## The decoder's speed clears when the signal goes

The "Decoder hears N wpm" line beside the keyer used to keep the last
station's speed for good. It now goes back to "Decoder speed —" as soon
as the decoder stops hearing a signal, so the number you see always
belongs to someone sending now. The second display's copy of the CW panel
does the same.
