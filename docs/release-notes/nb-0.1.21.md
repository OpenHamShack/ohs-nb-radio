# OpenHamShack QO-100 NB 0.1.21

The update banner shows one line (`nb-0.1.21.txt`); this is the whole story,
for anyone who wants it. Installed copies from 0.1.16 on offer this release
by themselves.

## FT8: replies go in the right slot

- **No more ~27 s wait.** Click a station in the band activity and your
  call goes out in your very next slot - in the one you are in, if it is
  yours. Before, a click a moment after your slot began waited a whole
  cycle, so the other station had often given up.
- **Auto seq is no longer a cycle late.** A reply decoded before your slot
  starts goes in that slot, as in WSJT-X; one that arrives after your
  transmission has begun goes in your next.
- **A late start, up to 6 s, as WSJT-X does it.** Up to 2 s into your slot
  the whole message goes, that much late. After that, up to 6 s, it starts
  at once from the point a punctual one would have reached, and the opening
  is dropped. The station you call still decodes it, knowing its own call;
  a station decoding blind manages up to about 4.5 s.
- Anything still waiting to go for your last QSO - an RR73 repeat, say - is
  dropped when you click a new station.

## FT8: TX = RX

- A new **TX = RX** switch puts your transmit offset on your receive offset
  and keeps them together while it is on: a click on a station, or on
  either marker in the zoom scope, moves both. **Hold TX freq** is greyed
  while it is on.

## FT8 and FT4: a bigger band activity list

- In FT8 and FT4 the band activity takes most of the window: the wide scope
  shrinks to a strip and the zoom scope narrows. Drag the dividers as you
  like; FT8/FT4 remember their own layout, separately from the other modes'.
- **Ctrl and the mouse wheel** (or **Ctrl +** / **Ctrl -**) over the list
  make its text larger or smaller, and the size is kept.

## Control pad: the keys no longer flicker

- The Ajazz AKP03E drops a computer that sends it nothing for about 39
  seconds. Once its keys were drawn NB sent nothing, so every 39 s the pad
  went blank and every key was drawn again - a flicker across the whole pad.
  NB now sends the pad a keep-alive every 10 seconds, so it stays connected
  and the keys stay put.
