# IC-9700 as an external transmitter: protocol research

What OpenHamShack NB's CI-V and rigctld drivers (`ohscore/rig/civ.py`,
`ohscore/rig/rigctl.py`) and their emulators (`civsim.py`, `rigctlsim.py`)
were written from. Researched 5 October 2026 for Ray, who receives QO-100
with NB and a Pluto and transmits with an IC-9700 on 23 cm into an
upconverter. **No IC-9700 has been connected to any of this code.** Anything
the documents below leave open is marked **[unverified]** and needs Ray's
radio to settle.

## Sources

- **CIV** - Icom, *CI-V Reference Guide, IC-9700*. Icom's own servers did not
  answer in this session; cited from the unmodified copy at
  <https://www.rigpix.com/icom/ic9700_civ_v2.pdf>. "CIV p.N" is the
  document's printed page.
- **Manual** - Icom, *IC-9700 Instruction Manual*,
  <https://rigpix.com/icom/ic9700_manual.pdf>; **Advanced** - *IC-9700
  Advanced Manual*, <https://www.rigpix.com/icom/ic9700_advanced.pdf>.
- **CI-V 1993** - Icom, *CI-V System* manual (1993),
  <https://cryptomuseum.com/ref/protocol/civ/files/CIV_manual_1993_v3.pdf>.
- **Brochure** - Icom France, IC-9700 specification sheet,
  <https://icomfrance.com/uploads/files/produit/doc-IC-9700-en.pdf>
  (frequency ranges, checked against icomamerica.com).
- **rigctld(1)** - Hamlib manual page,
  <https://hamlib.sourceforge.net/html/rigctld.1.html>, and for what the
  manual does not list, Hamlib's source on GitHub (`tests/rigctl_parse.c`,
  `include/hamlib/riglist.h`, `include/hamlib/rig.h`, `rigs/icom/icom.c`,
  `rigs/icom/ic7300.c`).

## CI-V framing and defaults

| item | value | source |
| --- | --- | --- |
| Frame, controller to radio | `FE FE <radio> <controller> <cmd> [<sub>] [data] FD` | CIV p.3 |
| Frame, radio to controller | `FE FE <controller> <radio> <cmd> [<sub>] [data] FD` | CIV p.3 |
| OK / NG | `FE FE E0 A2 FB FD` / `FE FE E0 A2 FA FD` | CIV p.3 |
| Read or set | a command listed as send/read reads when sent without a data area and sets when sent with one | CIV p.11-12 (asterisk legend) |
| Radio address | **A2h** default ("A2h is the default address of the IC-9700") | Manual p.8-13 |
| Controller address | E0h | CIV p.3 |
| CI-V USB Baud Rate | default **Auto** | Manual p.8-13 |
| CI-V USB Port | default "Unlink from [REMOTE]": the USB port and the REMOTE jack are separate CI-V channels | Manual p.8-13 |
| CI-V USB Echo Back | exists, default **OFF** | Manual p.8-14 |
| Echo mechanics with it ON (does the radio resend the controller's frame before answering?) | **[unverified]** - neither document spells it out. The driver skips any frame not addressed to it, so either way works. | - |
| CI-V Transceive | default **ON**: the radio sends command `00` (frequency) to address `00` when its frequency changes, from any source; no reply is expected. Readable as `1A 05 01 27` | Manual p.8-13, CIV p.7, p.4-5 |
| Collisions | on the single-wire REMOTE bus the controller detects a collision and sends the jammer code `FC` | CI-V 1993 §1-6, §5-4 - **[unverified]** for the 9700, and not documented for USB at all. The driver drops any frame containing `FC`. |
| USB(A) / USB(B) | USB(A) always carries CI-V; USB(B) is configurable, default OFF | Manual p.8-13 |

## Commands the drivers send (the whole whitelist)

CAT PTT and the data-mode writes were added on 12/10/2026 (Brian: NB may key
the 9700 for its own digital-mode overs, as WSJT-X does, and put it in the
data variant for them). ohscore/rig/base.py says why PTT sits behind a permit.

| command | bytes (controller to radio) | reply | source |
| --- | --- | --- | --- |
| Read frequency | `FE FE A2 E0 03 FD` | `FE FE E0 A2 03 <5 BCD> FD` | CIV p.4, p.13 |
| Set frequency | `FE FE A2 E0 05 <5 BCD> FD` | `FB` or `FA` | CIV p.4, p.13 |
| Read mode | `FE FE A2 E0 04 FD` | `04 <mode> <filter>`: mode `00` LSB `01` USB `02` AM `03` CW `04` RTTY `05` FM `07` CW-R `08` RTTY-R `17` DV `22` DD; filter `01`-`03` FIL1-3 | CIV p.13 |
| Set mode (LSB / USB) | `FE FE A2 E0 06 00 FD` / `FE FE A2 E0 06 01 FD` | `FB` or `FA` | CIV p.13 (mode bytes as for Read mode). Sent with no filter byte, so the radio keeps that mode's filter. [unverified]: that a 9700 accepts `06` without the filter byte, and which filter it then uses (the intent: its own for that mode). If it answers FA, send `06 <mode> 01`. |
| Read DATA mode | `FE FE A2 E0 1A 06 FD` | `1A 06 <00/01 off/on> <filter>` | CIV p.11, p.17 |
| Read transmit state | `FE FE A2 E0 1C 00 FD` (no data byte: a **read**) | `1C 00 00` receive, `1C 00 01` transmit | CIV p.11 |
| Set DATA mode (since 12/10/2026) | `1A 06 01 <filter 01-03>` on, `1A 06 00 00` off | `FB` or `FA` | CIV p.17 ("When 00 is set, also set 00 to" the filter). The filter written is the one `04` reports, so the operator's stays. Sent after `06` when the mode itself must change. **[unverified]**: whether `06` turns DATA off on a real 9700 (the emulator assumes it does, so the driver always sends `1A 06` after). |
| Read MOD Input (since 12/10/2026) | `1A 05 01 15` DATA OFF MOD, `1A 05 01 16` DATA MOD | `1A 05 01 1x <00-05>`: 00 MIC, 01 ACC, 02 MIC+ACC, 03 USB, 04 MIC+USB, 05 LAN | CIV p.7 (SET > Connectors > MOD Input). With a value byte these are menu **writes**, which the whitelist refuses. |
| PTT on / off (since 12/10/2026, **only under the digital over's permit**) | `FE FE A2 E0 1C 00 01 FD` / `... 1C 00 00 FD` | `FB` or `FA`; confirmed by reading `1C 00` straight after | CIV p.11 |

### The setup assistant's commands (since 12/10/2026)

Brian asked for an IC-9700 setup assistant in NB's Transmitter settings
(`ohsnb/rigsetup.py`) that finds the address, checks the radio's settings
and, with one confirmation, sets them - and can put them back as they
were. These are all it sends besides the table above. Reads are always
allowed; each write only under a `SetupPermit` naming that exact body
(`ohscore/rig/base.py`), armed by the assistant for the writes the
operator has just confirmed. Page numbers are the printed ones of the
copy in `~/build/civ9700/civ.txt`.

| command | bytes (controller to radio) | reply | source |
| --- | --- | --- | --- |
| Read transceiver ID | `19 00` | `19 00 <id>` **[unverified]**: the guide lists the command, not its reply; the assistant needs only that something answered from that address | CIV p.5 |
| Read Po meter | `15 11` | `15 11 <0000-0255 BCD>`: 0143 = 50 %, 0213 = 100 % | CIV p.4 |
| Read ALC meter | `15 13` | `15 13 <0000-0255 BCD>`: 0000 minimum to 0120 maximum | CIV p.5 |
| Read / set satellite mode | `16 5A` / `16 5A 00` off, `16 5A 01` on | `16 5A <00/01>`; `FB` | CIV p.5 |
| Read band selection | `07 D2` | `07 D2 <00 MAIN / 01 SUB>` (**[unverified]** reply layout) | CIV p.4 |
| Select MAIN / SUB | `07 D0` / `07 D1` | `FB` | CIV p.4 |
| Exchange MAIN and SUB bands | `07 B0` | `FB` | CIV p.4 |
| Read MAIN's frequency | `25 00` | `25 00 <5 BCD>`; `FA` in satellite mode | CIV p.11 ("Only MAIN band"), p.23 |
| Read / set USB MOD Level | `1A 05 01 13` / `1A 05 01 13 <0000-0255 BCD>` | the value; `FB` | CIV p.7 (SET > Connectors > MOD Input > USB MOD Level) |
| Read RF POWER | `14 0A` | `14 0A <0000-0255 BCD>`: 0000 minimum to 0255 maximum (1200 MHz: 0.1-10 W, so 0 % is still 0.1 W) | CIV p.4; brochure |
| Set DATA MOD | `1A 05 01 16 <00-05>` | `FB` | CIV p.7 |

Levels are four BCD digits in two bytes, most significant first: 50 % is
`0128`, sent `01 28`. The asterisk legend (send/read, read-only, send-only)
is on CIV p.12.

Still open, to watch on Ray's radio: whether `07 B0` behaves the moment
satellite mode has been switched off (the assistant switches it off first,
then reads MAIN again before exchanging).

#### The meters on a real 9700 (measured 12/10/2026)

Ray's first level set (23 cm into a dummy load, USB MOD Level 50 %,
Windows) said the ALC moved "even at -40 dB". Brian's own IC-9700 was
then measured on shack, Brian present: 2 m (144.750) into a dummy load,
USB-D, USB MOD Level 50 %, a 1500 Hz tone into the USB Audio CODEC (ALSA
mixer 0 dB) at the dBFS shown, keyed by CI-V, Po and ALC read 0.5 s
after key-up (`~/build/nb0115/ic9700-alc-po-2m-20261012.log` on shack,
script `civlevel.py` beside it; first reading of each over):

| RF POWER | no tone | -40 | -34 | -28 | -22 | -16 | -10 .. 0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 13 (5 %) | ALC 4, Po 1 | 72, 20 | 152, 21 | 112, 22 | 141, 22 | 159, 23 | ~160, 23 |
| 64 (25 %) | 4, 2 | 5, 26 | 75, 3 | 59, 70 | 106, 83 | 139, 83 | ~140, 83 |
| 128 (50 %) | 3, 1 | 38, 3 | 83, 27 | 25, 141 | 89, 111 | 119, 140 | ~121, 143 |

(cells ALC, Po.) What follows:

- **The ALC meter reads with any audio at all**, -40 dBFS included, runs
  past 0120 (to about 160), and reads higher at a lower RF POWER: on the
  9700 the ALC is what holds the output to the RF POWER setting. "Set
  the level where the ALC just starts to move" cannot work on it; Icom's
  own wording is "within the ALC zone".
- **Po is the usable signal**: it rises with the level and then goes flat
  at the setting (the knee): near -28 dBFS at 50 %, near -22 at 25 %,
  and already flat at -40 dBFS at 5 % - where no level of NB's changes
  the power.
- **The real meter drops out**: Po 3 at -34 dBFS between 26 and 70 (25 %),
  111 between 141 and 140 (50 %). Read more than once.
- Keyed with no audio the ALC reads 3-4, not 0.

Ray's own 9700, the same day (23 cm into a dummy load, RF POWER 59/255,
USB MOD Level 50 %, Windows; the standalone IC-9700 Diagnostic 1.1 on
branch tools/ic9700-diag, once it played into the 9700's own CODEC):

| dBFS | no tone | -40 | -37 | -34 | -31 | -28 | -20 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Po | 0 | 14 | 28 | 49 | 74 | 75 | 76 |
| ALC | 5 | 5 | 5 | 5 | 13 | 39 | 99 |

Here the ALC behaves as a textbook says - its keyed baseline until the
Po knee (-31 dBFS), then rising - unlike Brian's at 5 % on 2 m. Both
happen, so the knee is found from Po, and the ALC is a cross-check and a
ceiling. Po reached half power 65 ms after the key-up with the audio
already playing, and fell under 10 % 210 ms after the unkey. SWR read
50-58 raw into the dummy load. His radio answered CI-V only at 19200
baud, on COM4 (COM6 the second CP2102N port), and his PC has two USB
Audio CODECs - the second is his FTDX10's - which is why NB's name match
first chose the wrong one.

The level set (ohsnb/rigsetup.py) has used Po's knee since, keeping the
lowest level that makes nearly all the flat power (-31 dBFS on Ray's),
with the ALC as a ceiling; civsim's `real_9700()` is shaped on both
tables.

Frequency BCD: five bytes, least significant pair first, each byte's high
nibble the more significant digit: byte 1 = 10 Hz / 1 Hz ... byte 5 = 1 GHz /
100 MHz (CIV p.4-5). 1268.123456 MHz is `56 34 12 68 12`. The 9700's bands
stop at 1300 MHz, so byte 5 never exceeds `13`. (An example frame worked
from that rule, not quoted by Icom: 145.225125 MHz reads back as
`FE FE E0 A2 03 25 51 22 45 01 FD`.)

### Never sent: commands that transmit or change power

The driver is a whitelist (above) because the same command keys the radio
with one more byte:

| command | why it is never sent | source |
| --- | --- | --- |
| `1C 00 01` (and `1C 00 00`) **without the permit** | the set form of the transmit state: `01` **keys the radio**. Never sent at all until 12/10/2026; since Brian decided NB may key the 9700 for its own digital overs (as WSJT-X does, never voice), sent only by the digital over path under its `PttPermit` (ohscore/rig/base.py) | CIV p.11 |
| `1A 05 <item> <value>` | any menu write (levels, CI-V settings, DATA OFF MOD...) except DATA MOD and USB MOD Level, and those two only under the setup assistant's permit | CIV p.7 |
| `17 <text>` | sends CW (transmits, depending on the TX switch / break-in) | CIV p.5, p.13 |
| `28 00 <01-08>` | transmits a voice memory | CIV p.12 |
| `1A 0B` | picture TX - **[unverified]** exact grouping | CIV (PDF extraction ambiguous) |
| `22 00` | DV TX data - **[unverified]** whether it alone starts a transmission | CIV |
| `14 0A <level>` | sets RF power (the read form, `14 0A` alone, is sent since 12/10/2026; the write never) | CIV p.4-5 |
| `1C 01` | antenna tuner: not in the 9700's table at all (no tuner) | CIV |

`tests/test_rig_civ.py` checks that every one of these is refused before a
byte is sent, that a session of polling, retuning, knob turns, keying and a
lost link sends none of them, and - so that the check means something - that
the emulator does see a `1C 00 01` sent by hand and keys.

### Main, Sub, VFOs and satellite mode

Ray uses the 9700 as an ordinary transceiver on 23 cm, not in satellite
mode; the driver selects nothing and talks to whatever band is MAIN.

- `07 00` / `07 01` VFO A / B (both NG in satellite mode), `07 A0` A=B,
  `07 B0` exchange MAIN/SUB, `07 D0` / `07 D1` select MAIN / SUB, `07 D2`
  read the selection (CIV p.4). Sent only by the setup assistant (above):
  `07 D2` to read, `07 B0` / `07 D0` / `07 D1` under its permit.
- `16 5A` satellite mode off/on (CIV p.5). Read, and switched off or back
  on, only by the setup assistant under its permit.
- In satellite mode MAIN is the downlink (receive) and SUB the uplink
  (transmit): Manual p.7-1's key table ("MAIN - Downlink frequency", "SUB -
  Uplink frequency"). An Icom brochure snippet says the reverse; the manual
  is taken as right - **[unverified]**, irrelevant unless someone uses NB with
  the radio in satellite mode.
- `03` / `05` act on the selected band (MAIN unless `07 D1` was sent) -
  inferred from the command table and the operating chapter, not stated
  in one sentence - **[unverified]**. So NB needs **the 23 cm band on MAIN**;
  if it is not, the radio either answers NG to a 23 cm frequency or tunes
  the other band, and NB's Transmitter status says the frequency was refused.
- `25 <00|01> <5 BCD>` reads/sets the selected/unselected VFO, MAIN band
  only; NG in satellite mode (CIV p.23; Hamlib `icom.c` "IC-9700 ... cannot
  execute 0x25/0x26 commands in satmode"). Not used: `03`/`05` are enough.

### Setting the frequency while transmitting

No Icom document and no Hamlib comment says whether `05` (or `25`) is
obeyed, refused or ignored while the 9700 is transmitting. The only
documented NG for `25` is satellite mode, regardless of TX (CIV p.23).
Satellite programs (SatPC32, gpredict through Hamlib) retune during passes,
but in satellite mode, where the uplink is SUB and the question is a
different one; forum threads on them do not isolate it. **[unverified]**.

So OpenHamShack NB never sets the frequency while the 9700 is transmitting: TX
lock measures during the over and the correction is sent the moment the
radio is back on receive. If Ray's radio turns out to retune cleanly
mid-over, `RigLink(may_set_keyed=True)` is the one switch to change.

### CW carrier position

Icom transmits CW on the displayed frequency and offsets the receiver by
the CW pitch: Manual p.4-11 (zero-beat: "match your transmit frequency
exactly ... by matching the audio tone") with the Advanced Manual's
CW-normal/reverse carrier-point diagram. Not one sentence anywhere -
**[unverified]** as stated, and it matters: TX lock takes its corrections from
a CW carrier and expects it on the dial. If the carrier turns out to sit a
pitch away, every correction would be off by the pitch.

## The IC-9700's frequency ranges

Transmit equals receive per band (one specification table). From the
Brochure, checked against icomamerica.com:

| band | USA / EXP | EUR (incl. UK) | ITR |
| --- | --- | --- | --- |
| 2 m | 144-148 MHz | 144-146 MHz | 144-146 MHz |
| 70 cm | 430-450 MHz | 430-440 MHz | 430-434, 435-438 MHz |
| 23 cm | 1240-1300 MHz | 1240-1300 MHz | 1240-1245, 1270-1298 MHz |

OpenHamShack NB checks the IF the upconverter needs against the **EUR** ranges
(Ray is in the UK; they are the narrower set, and 23 cm is the same
everywhere except Italy). The UK allocation runs to 1325 MHz but the radio
stops at 1300 regardless.

## Upconverters (examples)

The LO is a setting with no default: NB will not guess it. Examples of
what people use, all **low-side (IF + LO = uplink), non-inverting**:

| unit | IF | LO | source |
| --- | --- | --- | --- |
| DXPatrol MK4 upconverter | 1296 MHz (also 28 / 144 / 432, DIP-selected) | 1104 MHz for the 1296 MHz IF | manual hosted at wimo.com (DXPatrol, dxpatrol.pt) |
| SG-Lab 13 cm transverter | 432 MHz class | jumper-selected ~1870-1972 MHz (output 2301-2403 MHz) | SG-Lab programming guide via 3fs.net.au; passion-radio.com |
| F1OPA upconverter | 144 MHz / 432 MHz | 2256 MHz / 1968 MHz | passion-radio.com |
| Kuhne / DB6NT, BaMaTech | - | no 13 cm transmit upconverter page with IF/LO figures found | **[unverified]** |

High-side (LO - IF = uplink) mixing exists in principle (a ~3.7 GHz LO
with a 23 cm IF) and NB supports it - the spectrum is inverted, so the
radio's USB goes up as LSB and its knob runs backwards - but no product
above uses it.

## Hamlib rigctld

| item | value | source |
| --- | --- | --- |
| IC-9700 model | **3081** (`RIG_MODEL_IC9700 = RIG_MAKE_MODEL(RIG_ICOM, 81)`); caps in `rigs/icom/ic7300.c`, address A2h in `icom.c` | `include/hamlib/riglist.h` |
| Default TCP port | 4532 (`-t`) | rigctld(1) |
| Protocol | one command per line; values one per line; set commands and errors answer `RPRT n`, 0 success, negative a `rig_errcode_e` (e.g. -9 rejected by the rig, -14 bus busy) | rigctld(1); `rig.h` |
| `f` | get frequency: Hz | rigctld(1) |
| `F <Hz>` | set frequency: `RPRT 0` | rigctld(1) |
| `t` | get PTT: 0 receive, 1 transmit, 2 transmit (mic), 3 transmit (data) | rigctld(1); `rig.h` |
| `m` | get mode: mode name, then passband Hz (`USB`, `LSB`, `CW`, `CWR`, `PKTUSB` ...) | rigctld(1) |
| `M <mode> <passband>` | set mode: `RPRT 0`. Sent as `M USB 0` / `M LSB 0`; passband 0 is `RIG_PASSBAND_NORMAL`, the rig's usual width for the mode (-1 would keep FM's) | rigctld(1); `rig.h` |
| `\chk_vfo` | `CHKVFO 0` or `CHKVFO 1`: whether rigctld runs with `--vfo` | rigctld(1) |
| `--vfo` (`-o`) | then `f`, `F`, `t`, `m` need a VFO name first (`f currVFO`, `F currVFO 1268000000`); `v`/`V` do not | rigctld(1); `rigctl_parse.c` (`ARG_NOVFO`) |
| `q` | ends this client's session, not the daemon | rigctld(1) BUGS |

The driver sends `\chk_vfo` once, then only `f`, `F`, `t`, `m`, `M USB 0` / `M LSB 0`,
`M PKTUSB 0` / `M PKTLSB 0` (the data variants, since 12/10/2026) and - only
under the digital over's permit, since 12/10/2026 - `T 1` / `T 0` (with
`currVFO` when `--vfo` is on). `T 1` is `RIG_PTT_ON`, which Hamlib's Icom
backend sends as `1C 00 01`. Never sent, checked before every send:
`T` with any other value, `\set_ptt`, `b` / `\send_morse` (keys CW),
`\send_voice_mem` (keys the radio; **not in the manual page**, found only in
the source), `L` (set level, including `RFPOWER`), `M`, and the
undocumented `\halt` (stops the daemon).

IC-9700 specifics in Hamlib's source (`rigs/icom/icom.c`, `ic7300.c`):
`get_vfo` is not wired for the 9700 ("can indicate Main/Sub band selection,
but not VFO A/B"); satellite mode disables the `25`/`26` fast path; "split
on Main/Sub does not work; only Main VFOA/B and SubRx/MainTx split works".
None of that matters for one band used as a plain transceiver. Nothing
found ties `get_freq` to the transmit state **[unverified]**.

## What Ray's radio has to confirm

Confirmed on air 07/10/2026 (Ray, Windows, NB 0.1.8, DXPatrol MK4): items 1
and the MAIN half of 2 - NB tuned the radio over CI-V and his signal landed
on frequency. The rest are still open, and so is 7.

1. CI-V answers on the USB port at the chosen baud with address A2h (the
   Test connection button reads the frequency and nothing else).
2. With the 23 cm band on MAIN, `05` moves it and `03` reads it back; with
   23 cm on SUB, what happens (NB expects NG or the wrong band, and says so).
3. A CW carrier lands on the dial (TX lock's correction depends on it).
4. `1C 00` reads 01 within one poll of pressing PTT, and 00 after.
5. Whether echo appears with CI-V USB Echo Back ON (the driver should not
   care either way).
6. The upconverter's actual LO error: the first CW over shows it as
   "LANDED", and the correction after it should bring the second over
   within a few hertz.
7. That `06 00` / `06 01` (set LSB / USB, no filter byte) is accepted, so
   NB's FM-to-SSB switch works (added 08/10, after Ray's on-air use).
