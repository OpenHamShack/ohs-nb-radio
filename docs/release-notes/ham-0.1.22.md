# OpenHamShack Radio 0.1.22

The update banner shows one line (`ham-0.1.22.txt`); this is the whole
story, for anyone who wants it. Installed copies from 0.1.16 onwards offer
this release by themselves, on Windows, Linux and macOS.

## Fixes

- **No tuning or mode change while an Icom radio is transmitting.** Radio
  reads the radio's transmit state again straight before every frequency
  or mode command it sends over CI-V. If the radio has gone to transmit in
  the meantime (Radio's own key-up, or your PTT), the command waits until
  the over ends instead of retuning the radio mid-over. A DATA mode change
  you asked for is still made, once the radio is back on receive.
