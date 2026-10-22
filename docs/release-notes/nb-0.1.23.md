# OpenHamShack QO-100 NB 0.1.23

The update banner shows one line (`nb-0.1.23.txt`); this is the whole story,
for anyone who wants it. Installed copies from 0.1.16 on offer this release
by themselves, on Windows, Linux and macOS.

## Fixes

- **No tuning or mode change while an Icom radio is transmitting.** NB reads
  the radio's transmit state again straight before every frequency or mode
  command it sends over CI-V. If the radio has gone to transmit in the
  meantime (NB's own key-up, or your PTT), the command waits until the
  over ends instead of retuning the radio mid-over. A DATA mode change
  you asked for is still made, once the radio is back on receive.
