# OpenHamShack QO-100 NB user guide

OpenHamShack QO-100 NB is a transceiver for the narrowband transponder on QO-100 (Es'hail-2). It runs on your own computer - a Linux laptop, a Raspberry Pi 400/500, or Windows 10/11 - and works an ADALM-Pluto, Pluto+, LibreSDR or Pluto nano directly: the program does the receiving, the demodulating and the transmitting itself. It is one window, used at the machine it runs on; there is no browser console and nothing to log in to.

It starts on a built-in **simulator** - a simulated QO-100 downlink with beacons, other stations and your own signal coming back - so you can learn every control with no dish and no radio, and nothing can transmit by accident.

Transmit only within your amateur licence, and never stronger than the beacon. OpenHamShack QO-100 NB helps with both, but the licence condition is yours to keep.

**This is an early preview.** It has received the real QO-100 downlink with a Pluto, beacon lock and all, but it has not yet transmitted on air: transmitting and TX lock are proven only against the simulator. See [Not yet verified](#not-yet-verified), at the end, before you rely on it.

## What it is, and what it is not

It is:

- A receiver for the whole 500 kHz transponder, with a bandscope and waterfall across it, a zoomed scope around your frequency, and the bandplan drawn along the top.
- A transmitter for the Pluto family, full duplex, so you hear and see your own signal come back from the satellite.
- Or a receiver beside your **IC-9700**: NB tunes it, follows its knob, shows where your signal lands and corrects it between overs, while you key the radio yourself for voice - and, if you allow it, keys it by CAT for NB's own digital modes (see [Transmitting with an IC-9700](#transmitting-with-an-ic-9700)).
- **Beacon lock**: it measures your LNB's error against the beacons and corrects it continuously, so stations sit on the frequencies the bandplan gives.
- **TX lock**: while you transmit it finds your own signal in the downlink and corrects the uplink until your signal lands exactly where the dial says.
- **A beacon-level guard**: it measures your downlink against the beacon and, by default, turns your power down if you get within 6 dB of it.
- Modes: USB and LSB voice, CW (keyer and decoder), FT8 and FT4, PSK31/63/125, RTTY 45.45 baud / 170 Hz, FreeDV (700C, 700D, 1600, 2020), SSTV (receive and send), and AM for listening to the beacons.
- A logbook with ADIF export, and memories.

It is not:

- A replacement for WSJT-X, fldigi or FreeDV-GUI. FT8 and FT4 are decoded and sent by a port of WSJT-X's own decoder and encoder, and FreeDV by `libcodec2`, but the operating screens here are simpler than those programs'.
- A DATV transmitter. That is the sibling project, OpenHamShack.
- A remote station. It is used at the computer it runs on.
- A sequencer for transverters, amplifiers or relays. It drives the Pluto's own output, or tunes an IC-9700 (keying it by CAT only for NB's digital modes, when you allow it), and nothing else; there is no PTT line out.
- A recorder. There is no audio or IQ recording yet.

## What you need

- A computer: a Linux laptop (Debian 12 or 13, Ubuntu 24.04 or later, Mint built on those), a Raspberry Pi 400/500 on Raspberry Pi OS, or Windows 10/11 64-bit. A screen at least 1024 × 600 (see [Window sizes and text size](#window-sizes-and-text-size)).
- To transmit and receive: an **ADALM-Pluto, Pluto+, LibreSDR or Pluto nano**, with whatever filter, amplifier and dish feed your 2.4 GHz uplink needs. Or, to transmit, an **IC-9700** into an upconverter to 13 cm, with the Pluto (or another SDR) receiving.
- To receive only: the same, or (Linux only) an RTL-SDR, Airspy, SDRplay or HackRF through SoapySDR.
- A 10 GHz LNB on the dish. The usual consumer PLL LNB has a 9750 MHz local oscillator; OpenHamShack QO-100 NB measures its error against the beacons, so you do not need to know it.
- A sound card (the laptop's own is fine) and a microphone for voice. With no sound card the program runs silent.
- For FT8 and FT4 on Linux: nothing more with the `amd64` and `arm64` packages, which carry their own encoder and decoder; with the `all` package, WSJT-X (its `jt9` decodes and its `ft8code`/`ft4code` encode). Installed beside the others, WSJT-X's `jt9` is the fallback decoder and checks every slot's decodes. The Windows installer carries what it needs.

## Installing on Linux

Download the package for your computer from the website and check it against the SHA-256 printed beside it: `openhamshack-nb_<version>_amd64.deb` for a PC or laptop, `openhamshack-nb_<version>_arm64.deb` for a Raspberry Pi 4, 400, 5 or 500 running 64-bit Raspberry Pi OS, and `openhamshack-nb_<version>_all.deb` for anything else. `dpkg --print-architecture` says which you have. The first two carry OpenHamShack QO-100 NB's own FT8/FT4 encoder and decoder; the `all` one makes and decodes FT8 and FT4 signals with WSJT-X's `ft8code`, `ft4code` and `jt9` instead, and is otherwise the same.

```
sha256sum openhamshack-nb_*.deb
sudo apt install ./openhamshack-nb_<version>_amd64.deb
```

Use `apt install ./…` rather than `dpkg -i`: apt fetches what the package needs from your normal repositories in the same step. It needs `python3-numpy`, `python3-pyqt6` and `python3-pyaudio`, and by default also installs these **recommended** packages, each of which adds one feature:

| Package | What it adds |
| --- | --- |
| `python3-libiio` | The Pluto family (ADALM-Pluto, Pluto+, LibreSDR, Pluto nano) |
| `libiio-utils` | Provides `iio_info`, which the Pluto's USB permission rule needs to work at all, and which is handy for checking the radio is there (`iio_info -s`) |
| `libad9361-0` | The Pluto's own routine for low sample rates. Without it OpenHamShack QO-100 NB loads its own filter instead (see [Choosing a radio](#choosing-a-radio)) |
| `avahi-daemon` | Lets **Find** in Settings see a Pluto by name on the network, and stops libiio's scan failing outright |
| `wsjtx` | FT8 and FT4 with the `all` package (its `jt9` decodes, its `ft8code`/`ft4code` encode); with the others, the fallback decoder and the check on every slot |
| `libcodec2-1.2` or `libcodec2-1.0` | FreeDV (apt picks whichever your release has) |
| `python3-soapysdr` | Receive-only SDRs through SoapySDR |
| `python3-zeroconf` | **Find controllers** in Settings › Controller (without it, type the controller's address) |

And for a receive-only SDR, its SoapySDR module: `soapysdr-module-rtlsdr` or `soapysdr-module-airspy`.

A package you leave out never stops the program: the feature that needs it says which package to install, and everything else works.

Start **OpenHamShack QO-100 NB** from the applications menu, or `openhamshack-nb` in a terminal.

**Or the AppImage**, one file for any 64-bit PC running Linux from Debian 12 or Ubuntu 22.04 on, with no installing: download `OpenHamShack-QO-100-NB-<version>-linux-x86_64.AppImage`, check its SHA-256, make it executable (`chmod +x`) and run it. It carries its own Python, Qt and libraries; a Pluto needs the system's libiio (`sudo apt install libiio0` or your distribution's equivalent), and WSJT-X's `jt9` for FT8 and FT4 decoding if you have it installed.

## Installing on Windows

Download `openhamshack-nb-<version>-setup.exe` and double-click it. It installs for you alone into `%LOCALAPPDATA%\Programs\OpenHamShack QO-100 NB` (the Pluto's USB drivers, below, are the one part that asks for administrator permission), and adds **OpenHamShack QO-100 NB** and **OpenHamShack QO-100 NB (console)** to the Start menu. The console one is the same program with a text window behind it, for reading an error at start-up.

**The installer is code-signed by 360 Technology** (from the release after 0.1.4; earlier ones are unsigned). Windows may still be cautious about a new publisher for a while:

- **SmartScreen** can say *Windows protected your PC* until the publisher has built up a reputation with Microsoft, which takes downloads and time. Check it names **360 Technology**, then choose **More info** and **Run anyway**.
- **Smart App Control** (Windows 11: Settings → Privacy & security → Windows Security → App & browser control → Smart App Control) blocked the unsigned installers outright. Signed ones should get further, but it also checks the third-party libraries inside, not all of which are signed by their makers, and it has not yet been tried with it On. If it blocks OpenHamShack QO-100 NB, it must be **Off** - and Windows will only turn it back on by resetting the PC, so decide on a test machine rather than someone's everyday one.
- A PC in **S mode** cannot run it at all.

The simulator, all the signal processing, beacon and TX lock, sound, FreeDV and FT8 are built in, and so is what a Pluto needs.

**For a Pluto, there is nothing to download.** libiio 0.26 is built in (a machine that also has ADI's libiio 1.0 is fine: OpenHamShack QO-100 NB uses its own copy). The USB drivers come with the installer: leave **Install the PlutoSDR USB drivers** ticked, and install **before plugging the Pluto in**. They give the Pluto its USB network adapter, so it appears at `ip:192.168.2.1` exactly as on Linux. Two questions follow, both from Windows: administrator permission for the drivers (the only part that needs it), then *Would you like to install this device software?* from Analog Devices International UC - answer **Install**. If either is refused, OpenHamShack QO-100 NB is still installed and the installer says the drivers are not; run it again with the option ticked. When the drivers are already there, the option is not shown at all. They appear in Settings → Apps as *PlutoSDR-M2k-USB-Win-Drivers* and stay if OpenHamShack QO-100 NB is uninstalled. With the Pluto plugged in, `ping 192.168.2.1` from PowerShell should answer; then **Find** in Settings › Radio lists it.

**FT8 and FT4 need no WSJT-X install**, and both send and receive: the installer carries OpenHamShack QO-100 NB's own FT8/FT4 encoder and decoder. (Up to 0.1.21 it also carried WSJT-X 2.7.0's decoder as the fallback; a WSJT-X you install yourself still takes that part.) The Country column's `cty.dat` comes with every package too, the `.deb` included.

Not built in: **receive-only SDRs through SoapySDR are Linux-only** for now.

Uninstalling (Settings → Apps, or the uninstaller in the Start menu) leaves your settings and log in `%APPDATA%\openhamshack-nb\`.

## Updates

From the release after 0.1.8, OpenHamShack QO-100 NB keeps itself up to date. A few seconds after it starts, and once a day while it runs, it fetches one small signed file from its website saying what the newest version is. Nothing about you or your computer is sent - only "openhamshack-nb/<version>", as any download would.

When there is something newer, a strip appears above the scopes: **OpenHamShack QO-100 NB 0.1.9 is available**, with **Install and restart**, **Later** and **What's new**.

- **Install and restart** downloads the new version, checks that it is exactly the file 360 Technology signed, and installs it. On Linux your system asks for your password (apt installs the package, as when you first installed it); then **Restart now**. On Windows the program closes, the installer runs by itself, and OpenHamShack QO-100 NB starts again.
- **It never installs or restarts while you are transmitting or recording.** The button waits, and says why; an over is never cut short.
- **Later** hides the strip until the next start. **What's new** opens the release notes on the website.
- **Help › Check for updates…** checks there and then, and says what the last check found - including why, when the site could not be reached or what it offered could not be proved genuine. Nothing that cannot be proved is ever installed, and a failed check never interrupts you.
- **Settings › Station › Check for updates** turns the automatic check off.

On Linux without a password prompt (no `pkexec`), the strip gives the command to type instead: `sudo apt-get install -y …`. A copy run from source never updates itself.

## The first time it starts

A short **Welcome** opens over the window: three steps, with **Back**, **Skip** and **Next** at the bottom.

1. **Your station.** Your callsign and locator (IO86 or IO86ha), and your **licence class**. The callsign and locator are used in macros, FT8 and JS8 messages and the log (JS8 will not send without a callsign); both can be left empty and filled in later in Settings › Station. A locator that is not a Maidenhead locator is refused with a sentence saying so. The licence classes offered are those of the country your callsign puts you in, and none is chosen for you. The class is **optional** in QO-100 NB: with it, the uplink is checked against your licence; without it, transmitting is not refused for it, and the transmit card keeps a reminder that the check cannot be made (see [Transmitting](#transmitting)). Where no licence is written into OpenHamShack for your country yet, there is no class to pick and it says so; you can enter your own in Settings › Licence.
2. **Before you transmit.** The four rules, and a tick box: *I understand, and I hold a licence that lets me transmit to QO-100.* **Leave it unticked to listen only.** Until it is ticked - here, or in Settings › Station - the TX button and every send button stay locked with a radio, and pressing them says why. The simulator is the exception: nothing it transmits leaves the computer, so it transmits either way.
3. **Your radio.** **Simulator** (the default), **ADALM-Pluto family** with its address (`ip:192.168.2.1` unless yours is elsewhere), or **Receive-only SDR**. **Start listening** finishes.

![The Welcome's first step: callsign, locator and, beside them, the licence classes of the callsign's country, none chosen.](screenshots/welcome-1.png)

![The Welcome's licence step. With a radio, transmit stays locked until the box is ticked.](screenshots/welcome-2.png)

**Skip**, on every step, closes the Welcome there and then. It marks the Welcome as seen and saves nothing else - not what you typed, not the radio, not the tick box - so you carry on with the radio already chosen (on a new install, the simulator), and the licence stays unacknowledged: a real Pluto stays receive-only until you tick the box in Settings › Station.

The Welcome shows once. **Help › Welcome…** opens it again.

The program never transmits at start, after a restart, after reconnecting to a radio, or after you save Settings. It comes up receiving, always.

## Choosing a radio

**Settings › Radio** (Ctrl + ,). Saving a change here restarts the radio; it comes back receiving.

![Settings › Radio: the radio, its address, Find, and the sample rate.](screenshots/settings-radio.png)

**Simulator.** A simulated downlink: the beacons, a noise floor shaped like the transponder's, SSB, CW, FT8, PSK31 and RTTY stations, an LNB that is 1.8 kHz out and slowly drifts, and your own transmission coming back a quarter of a second later, landing 11 kHz from where it was aimed until TX lock corrects it. Transmitting on it sends nothing anywhere, so it needs no licence: the TX button works on the simulator whether or not the licence box is ticked. Switch to a real radio and the lock is back at once. **Settings › Simulator** changes the errors, the drift and the other stations.

Whenever the simulator is the radio, a **SIMULATOR** badge sits beside *OpenHamShack QO-100 NB* at the top left, so its band is never taken for the real one; it goes as soon as a real radio is running. Hover over it to see why the simulator is in use. **Amber** with an *i*: Settings › Radio says Simulator (the default until you choose a radio), or `--device sim` was given on the command line for this run. **Red** with a warning triangle: the simulator is *standing in* for your radio, because the saved radio was not one OpenHamShack QO-100 NB knows or the settings file could not be read - it says which, once as a notice too. Choose your radio again in Settings › Radio. (A radio that is chosen but cannot be opened never falls back to the simulator: the radio stays stopped and the status line at the bottom says why.)

**Pluto family** - ADALM-Pluto, Pluto+, LibreSDR and Pluto nano are all the same AD936x chip behind the same driver, so they are one choice. Its **Pluto address** is a libiio URI:

- `ip:192.168.2.1` - a Pluto plugged in by USB (it is a USB network adapter as well as a radio). This needs no special USB permissions, so it is the one to try first.
- `ip:pluto.local` - the same by name, if `avahi-daemon` is running.
- `ip:<address>` - a Pluto+ or LibreSDR on your Ethernet, at the address your router gives it.
- `usb:<bus>.<device>.<interface>` - direct USB. On Linux this needs the udev rule from `libiio0` and `libiio-utils` installed (see [Troubleshooting](#troubleshooting)). On Windows a bare `usb:` is refused; use the full form **Find** lists.

**Find** asks libiio for every Pluto it can see, then tries `ip:192.168.2.1` and `ip:pluto.local` directly, and lists what answered; pick one and it fills the address in. Then **Save**.

**Sample rate**, 1.2 MS/s by default, is shared by receive and transmit. 1.2 MS/s keeps the transponder in the flat middle of the radio's filter and reaches almost the whole band from one transmit LO position. 600 kS/s uses about a third less processor but cannot transmit on uplink 2400.210-2400.290 MHz; the TX button says so there.

**Firmware that refuses the FIR.** Below about 2.08 MS/s the AD936x needs an extra filter (its ×4 FIR) loaded. OpenHamShack QO-100 NB uses `libad9361-0`'s routine if it is installed, and otherwise loads a filter of its own. Some firmware refuses both - the Pluto nano on Tezuka firmware does. OpenHamShack QO-100 NB then runs the radio at 2.4 MS/s and converts to 1.2 MS/s (or 600 kS/s) itself, automatically, and says so in a notice. It costs some processor time and nothing else; you do not need to do anything.

**SoapySDR (receive only)**, Linux only: RTL-SDR, Airspy, SDRplay, HackRF and anything else with a SoapySDR module. **SoapySDR device** takes its arguments (`driver=rtlsdr`, `driver=airspy`); **Detect** lists what is plugged in. The TX button stays locked with this radio: *This device is receive-only*.

**Receiver gain control** (Slow AGC by default) and **Receiver gain** are the SDR's own front-end gain. They apply as soon as you save, without restarting the radio. With a SoapySDR receiver both AGC choices mean the same thing: SoapySDR has a single automatic setting. On the simulator, manual gain moves everything up or down from its 40 dB level, signals and noise together.

## The window

![The main window on the simulator, in USB: the Voice workspace.](screenshots/main-usb-1920.png)

From the top:

**The header.** The frequency readout, the two lock badges, the TX button, and four small buttons: second display, Settings, Logbook and Keyboard shortcuts. (In a small window the four become one button with them on a menu: see [Window sizes and text size](#window-sizes-and-text-size).)

- **The readout** shows the **downlink** in large figures - the frequency you hear, 10 489.500 to 10 490.000 MHz - and the **uplink** beneath it (**UP**), the frequency your Pluto transmits on, including TX lock's correction. While you transmit both turn red. Next to the uplink are four chips: **RIT**, **XIT**, **SPLIT** and **STEP**, then the bandplan segment you are in, with its colour.
- **RX · beacon** and **TX · own signal**: the two lock badges, described under [Receiving](#receiving) and [Transmitting](#transmitting). Click one to pin its numbers open.
- **TX**: the transmit button. See [Transmitting](#transmitting).

**The bandscope and waterfall** across the whole transponder, with the bandplan strip along the top (hover over it for a segment's limits and what may transmit there), markers on the beacons, your receive passband in blue, where you would transmit as a dashed gold **TX** mark (red while you are on the air), and a **LANDED** flag where your signal actually came down. Decoded FT8 callsigns and text-mode characters are written on the waterfall where they were heard; labels never overlap or run off the edge, and give way rather than crowd.

**The zoom scope**, below on the left, is the few kHz around your frequency: your passband, its edges (drag them to set the filter), and in the digital modes the receive and transmit offsets (the transmit one gold while receiving, red on the air).

**Right-click** either scope for **What is this?**: what the signal there is, and one click to decode it or listen to it. See [What is this?](#what-is-this).

**The lower panel**, under a row of tabs that never moves: **Operate** (the panel for the current mode - see [Modes](#modes)), **Logbook**, **Memories**, **Beacon** (see [The multimedia beacon](#the-multimedia-beacon)) and **Band** (see [The band skimmer](#the-band-skimmer)). The mode's name and one line about it (*FT8 · 15 s periods*, *Q65 · 60 s periods*, or, in amber, what the mode is missing on this computer) are the first line inside Operate. The **Workspace** button sits at the right end of the tab row (below).

**The rail** on the right: **Mode**, **Transmit** (power, ALC, own signal against the beacon, the level guard, and a warning line under the power slider while there is something to warn about) and **Receive** (signal, SNR in the passband, volume and mute, AGC, gain with AGC off, the filter, the noise blanker and noise reduction, and the **Auto-tune** and **Best audio** buttons). How much of each card shows depends on the workspace. A compact **Receive** card is the signal, SNR, volume and mute and AGC, with a **▸ More receive controls** line that opens the rest in place (remembered for the workspace); a compact **Transmit** card is the power, own signal against the beacon and any warning, and the rest comes back while you are on the air.

- **The Mode card** groups the modes under three headings, always in the same order so a button stays where your hand learnt it: **Voice** (USB, LSB, CW, AM, FreeDV), **Digital** (FT8, FT4, Q65, JS8, PSK31, PSK63, PSK125, RTTY) and **Pictures & data** (SSTV, KG-STV, HSmodem). The heading of the group you are in is in the accent colour. Where room is short (the Watch workspace, a smaller window) the card shows one button per group instead, labelled with that group's most recent mode: click it to choose that mode, or its arrow for the group's menu. **Ctrl + E** opens a menu of every mode, recent ones first, and takes type-ahead: *q* goes to Q65, *psk1* to PSK125, *h* to HSmodem. **KG-STV** is not a radio mode: its button opens Beacon › KG-STV and, when nothing is on the air, tunes the receiver to KG-STV's 10 489.6249 MHz USB (see [KG-STV pictures](#kg-stv-pictures)).
- A mode with a small amber ring in its corner is missing something on this computer - hover over it, or choose it, to read what to install. A mode with a small grey dot receives but cannot transmit here (AM always; FT4 on Windows).
- **The Transmit card** shrinks to one line when this run cannot transmit - *Receive only this run* (started receive-only, or a receive-only SDR) or *Set up to transmit: Settings › Station*, with a button, when a real radio is waiting for the licence box. It never shrinks or hides while anything is on the air (an IC-9700 keyed at its own microphone included), while an over is armed, or while a transmit warning stands.

**The status strip** along the bottom: the radio (green dot running, red stopped, with the reason), **● REC** with the time and size while you record receive IQ (amber: red is kept for transmitting), its sample rate, the processor load (hover over it for how long the window takes to draw), **overruns** (times receive lost samples - a gap in the radio's stream, or the receiver more than two seconds behind; should stay at 0), the receive and transmit corrections, the multimedia beacon's quality while it decodes, and the time in UTC. A smaller window drops some of these into the radio item's tooltip.

**Notices** slide in at the top centre over the scopes: blue for news, amber for a warning, red for an error. They go by themselves (5, 10 or 16 seconds), stay while the mouse is over them, and a click dismisses one. Warnings about your transmission that last - over the beacon, the level guard's trim, the IC-9700 transmitting where NB would not - are not notices: they are one line on the **Transmit** card, under the power slider, which shows the most serious, changes in place, and goes when the condition does.

**View › Light theme** (Ctrl + T) changes to a light theme. The window remembers its size and position.

### Workspaces

A **workspace** decides how much room each part of the window gets. There are three, and the radio, the scopes' settings and every control are the same in all of them:

| | Digital | Voice | Watch |
| --- | --- | --- | --- |
| For | FT8, FT4, Q65, JS8, PSK, RTTY, and the Pictures & data modes | USB, LSB, CW, AM, FreeDV | looking at the whole band: who is where, what is that signal |
| Wide scope | a strip, a quarter of the height | 42 % of the height | two thirds of the height |
| Zoom scope | narrow and tall, never under 160 px | the biggest it gets | narrow |
| Rail | Mode in full; Transmit and Receive compact | every card in full, with the large S-meter | slim: Mode as three group buttons, Receive compact, Transmit hidden while nothing transmits |
| Lower panel | Operate | Operate | Band |

**Auto**, the default, follows the mode: Digital for the Digital and Pictures & data groups, Voice for the Voice group. Watch never comes by itself; you choose it.

- **The Workspace button** at the right end of the tab row says which is showing and whether it follows the mode (*auto*) or you chose it (*chosen*). Its menu, also **View › Workspace**, has **Auto - follows the mode**, **Digital**, **Voice**, **Watch** and **Reset this workspace's layout**.
- **W** steps to the next workspace (Digital, Voice, Watch) and keeps it; **Shift + W** goes back to Auto.
- **Choosing a mode** - a mode button, Ctrl + a number, Ctrl + E or the pad's MODE key - brings that mode's workspace and goes back to Auto, even from one you chose. Tuning from the Band list, from *What is this?*, from a memory or a click on a scope may change the mode but leaves the workspace alone, so browsing the band from Watch stays in Watch.
- Switching never changes the mode, the frequency, or anything about transmitting. Even in Watch, the Transmit card comes back in full while anything is on the air, an over is armed, or a transmit warning stands.

Drag the splitters between the scopes, the panel and the rail as you like: each workspace remembers its own, as proportions, so the same layout comes back in full screen or on a smaller screen. It also remembers which tab it last showed and which cards you opened. **Reset this workspace's layout** puts its defaults back.

![The Watch workspace: two thirds of the height for the band, a slim rail, and the Band list.](screenshots/main-watch-1920.png)

### Window sizes and text size

The window may be as small as **1024 × 600**. It lays itself out in one of three sizes:

- **Full**, from 1500 × 860: everything as described above.
- **Compact**, from 1180 × 700: the header drops the program's name, keeping its icon; the readout's figures shrink to fit (never losing a digit); the rail narrows, with every card compact and the Mode card as group buttons; the status strip moves the sample rate and processor load into the radio item's tooltip.
- **Tight**, below that, down to the minimum: the header is one line, with the four small buttons on one three-dot menu; the rail is hidden, and **Controls** on the tab row opens it as a drawer over the right-hand side (never over the wide scope, where you tune); the current mode sits on a button beside it, with every mode on its menu by group. The scopes keep at least 120 px for the wide one (40 px of it waterfall) and 160 px for the zoom. In Tight, the drawer opens by itself once when a transmit warning comes up or you key with Space or the TX button, and **Controls** turns red while either holds. **Esc** while you are transmitting or armed always unkeys first; with nothing on the air it closes the drawer.

**Text size** - **Settings › Display › Text size**, 100 %, 115 % or 130 % - makes every word and figure in the window larger when you save. The window's sizes are worked out from its size divided by the text size, so larger text moves the window into a smaller layout rather than cutting words off, and the minimum grows with it (1332 × 780 at 130 %). A text size whose minimum would not fit your screen is greyed, and hovering over it says why. The FT8 list's own size (Ctrl + wheel over it) is on top of this.

![FT8 in a 1024 × 600 window: the Tight layout, with the mode button and Controls on the tab row. The drawer has opened by itself for the transmit card's standing warning (no licence class chosen), and Controls is red while it stands.](screenshots/main-ft8-1024.png)

### Tuning

- **Click** a scope to tune there. What "there" means depends on the mode: in SSB the click is the dial; in CW the dial goes so the signal sounds at your CW pitch; in PSK and RTTY so it lands on the decoder at 1000 Hz; in FT8, FT4, FreeDV and SSTV the dial goes to a round frequency with the signal in the audio window.
- **Drag your passband** to tune by dragging. **Drag anywhere else** to pan the view (on the zoom scope, to move the zoom off-centre). A **middle double-click** puts the view back.
- **The mouse wheel** over a scope steps the dial by the current step. **Ctrl + wheel** zooms the scope. Over a **digit** of the readout, the wheel tunes by that digit.
- **Left / Right arrow** step down / up; **Shift** makes it ten steps, **Ctrl** 1 Hz. **[** and **]** make the step smaller and larger (1, 10, 50, 100, 500 Hz, 1, 5, 10 kHz), as do a click or the wheel on the **STEP** chip. Each mode has its own natural step - 50 Hz in SSB, 10 Hz in CW and PSK, 500 Hz in FT8 - chosen when you change mode.
- **F**, or a click on the big figures, opens the readout for typing. It takes what operators say: `10489.540`, `489.540` (MHz above 10 GHz), `540` or `540.25` (kHz above 10 489 MHz - the band is only 500 kHz wide), or an uplink `2400.040`, which it converts. **Enter** tunes, **Esc** cancels. A frequency outside the transponder is refused with a sentence.
- **RIT** (R) moves only what you hear, **XIT** (X) only where you transmit. The wheel over either chip sets its offset, 10 Hz a click, and turns it on.
- **SPLIT** (S) transmits on a second dial, which starts where you are.

### Adjusting a scope

The **Adjust** button in the top-right corner of each waterfall (just its slider glyph in a Tight window) opens that scope's adjustments, titled *Adjust the wide scope* or *Adjust the zoom scope*, in three tabs. The wide and the zoom scope each keep their own; the second display's big scope shares the wide scope's. Everything takes effect as you move it and is remembered.

- **Scope**: **Automatic scale** (the default) follows the noise floor; turn it off for a fixed **Top** (dBFS) and **Range** (dB), which start from where the automatic scale was, so nothing jumps. The dB labels follow. **Smoothing** averages the trace over time, from **raw** (each spectrum line as it comes) to 1 s; the default, 0.13 s, is the look it has always had. The waterfall and the peak ghost are not smoothed. **Display style**: **Standard** draws the scope's own fine bins, so a carrier or an FT8 tone stands at its full level and a wide signal, such as the 400-baud PSK middle beacon, reads its power per narrow bin and looks low beside them; **SDR Console-like** widens the resolution bandwidth to about 100 Hz and gives the trace a short hang and decay, so wide and narrow signals stand at about the relative heights SDR Console shows them. The waterfall follows the style. It changes only the picture: the level against the beacon, the transmit level warnings and beacon lock read the same either way. The resolution bandwidth the trace is drawn at is written in the frequency axis, after its unit ("RBW 18 Hz" on the zoom scope in Standard, at its usual 12 kHz span). **Colours…** opens Settings › Display at the scope colours.
- **Peaks**: **Peak hold** draws a faint ghost over the trace at each frequency's recent maximum. **Hold peaks for** Off, 1 s, 1.5 s (the default), 3 s, 10 s or ∞ (until cleared), **then fall at** 1-60 dB a second (default 10). **Clear peaks** starts the ghost again from the trace. **Label the strongest signals** (off by default) writes the frequency and level over up to **At most** signals (1-10, default 5) that stand **Over the noise by** at least 3-40 dB (default 10). The frequency is written as the axis writes it, in kHz above 10 489 MHz, to about the scope's resolution: "540.52  -62" on the zoom scope, "750.4  -44" on the wide one. One signal gets one label, however wide; labels are chosen twice a second and a label stays while its signal does, so they do not flicker or swap places.
- **Waterfall**: **Automatic levels** (the default, following the noise floor), or a manual **Floor** and **Contrast range**; the **Speed** (¼× to 2×); and the **Palette**.

![The wide scope's adjustments, Peaks tab, with the strongest signals labelled: the middle beacon, and the multimedia and upper beacons at the top of the band.](screenshots/scope-adjust-peaks.png)

They are on the scope because you adjust them while looking at the signal. The waterfall's levels, speed and palette are also in Settings › Display.

## Receiving

Choose your radio, put your dish on the satellite, and the bandscope fills. The first thing to look at is **RX · beacon**:

| Badge | Means |
| --- | --- |
| **SEARCHING** (amber, spinning) | Looking for a beacon. Beside it, how far either side: **±2 kHz** first around the correction it already has (from last time, from you, or from before it lost the beacon), then the whole search range (±50 kHz by default). |
| **LOCKED** (green) | Tracking it. The number beside it is the remaining error, normally within a few tenths of a hertz. Everything you see and hear is corrected. |
| **LOST** (red) | Had it, and lost it - a fade, the dish moved, the LNB jumped further than the tracker follows. Ten seconds later it searches again, where the beacon was first. Taking a lock needs the beacon 10 dB over the noise; once locked, it is kept down to 6 dB as long as what is measured is still the beacon, so a weak dish (8-10 dB) holds the lock instead of flickering between LOCKED and LOST. |
| **HOLD** (cyan, pause sign, dashed outline) | You stopped tracking: the correction is kept exactly as it was. Beside it, **no tracking**: nothing follows the LNB's drift until you go back to Auto. |
| **MANUAL** (cyan, knob, dashed outline) | You set the correction by hand; nothing tracks. |
| **OFF** | The radio is not running. |

Click the badge for the details: the mode, which beacon, the error, the drift rate in Hz per second, the total correction (**rxCorr** - how far high your LNB puts everything; *set by hand* when it came from you), the beacon's SNR and level, and - when beacon lock has turned something down - **Last refused**: what it looked at, where, and why it was not taken for the beacon. That line is what to send with an on-air report.

OpenHamShack QO-100 NB locks to the **middle beacon** (the 400 baud BPSK one at 10 489.750, which is GPS-referenced), and falls back to the **lower CW beacon** automatically if the middle one is not heard. The correction is kept between sessions, so the next start begins close. The correction is applied in software, so it moves smoothly; the radio itself is not retuned.

A loud station is not mistaken for the beacon. The middle beacon is found by its carrier-less BPSK, and plenty of other signals look like that to a simple detector - an SSB station drawing out its vowels, a carrier, PSK31. A candidate is taken for the beacon only if it also has what only the beacon has (its 400 Hz symbol rate, no carrier, a level that never pauses), and when the lower beacon is heard too, only if the two agree. A beacon found by a full search must be seen twice in the same place before it is locked to, and five times if it is far from where the beacon last was: the real beacon does not jump.

An unmodified LNB can be tens of kHz out and drifts as it warms up. If the badge never leaves SEARCHING, widen **Beacon search range** (Settings › LNB & locks, up to ±55 kHz). If your LNB is locked to GPS or a reference, tick **LNB is GPS-locked**: the beacon error is then mostly your Pluto's own crystal, and OpenHamShack QO-100 NB predicts the transmit correction from it before you ever key - from a correction beacon lock found itself, never from one you set by hand.

### Align your dish

**Radio › Dish alignment…** turns the window into a satellite finder for peaking the dish. It is receive only: while it is open, transmit is refused ("Dish alignment is open: close it to transmit"), and it will not open while you are transmitting.

![Dish alignment on a weak dish, with the tone and the phone page on. The address shown is an example.](screenshots/dish-alignment.png)

- **The big number** is the middle beacon's SNR - how far it stands over the noise either side of it, in dB, four times a second. Higher is better. A well-aimed dish normally puts it at about 15-20 dB; the weak dish this tool was first tried on read 8-10 dB. It reads 2-3 dB under the **Beacon SNR** in the RX badge's details, which measures the noise inside its own narrow filter.
- **Best** is the highest since the window opened. Sweep the dish slowly across the peak, then come back until the number reaches the best again; **Reset best** starts over (after moving the LNB's skew, say).
- **Transponder** is the whole passband's noise over the noise beside it, outside the passband: the satellite's own noise coming up out of your receiver's. It moves less than the beacon, but no station can fool it. On that weak dish it was about 1.4 dB. At 600 kS/s there is too little room beside the band to measure it, and it says so.
- Under them it says where the beacon was measured: where beacon lock has it, or - if beacon lock has not got it, as often happens while the dish is being moved - the strongest signal within ±15 kHz of where the beacon should be, and how far from there.
- **Tone** replaces the receive audio with a pitch that rises with the beacon (200 Hz at 0 dB, 50 Hz higher per dB), at your volume, so you can peak by ear with your eyes on the dish.
- **Phone page** serves the same numbers, and a tone, to a phone on the same network, so you can stand at the dish with the computer indoors. Off unless you tick it, and never kept on for next time. Choose the **Port** first if 8099 is taken (it says so if it is). Open one of the addresses it lists on the phone, and tap **Tone on** there (a phone plays sound only after a tap). The page answers only addresses on your own network - private, link-local, or a tailnet's 100.x - never one from the Internet, and it stops when you close the window. **On Windows**, the first time, Windows Defender Firewall asks whether OpenHamShack QO-100 NB may accept connections: allow it on **private networks**, or the phone cannot reach the page.
- **Receive gain is held** while it is open. An AGC turns the gain up as the signal falls and down as it rises - exactly the change you are looking for - so the gain is fixed where the AGC had it, and the AGC comes back when you close the window. Your setting in Settings › Radio is not changed. A manual gain is left as it is.

It works on a recording too (File › Play IQ recording…), which is a good way to see what it shows before going out to the dish.

### Telling it which signal is the beacon

If beacon lock has settled on the wrong signal, or will not find the beacon you can see, **right-click the beacon** on the bandscope or its waterfall (or the zoom scope) and choose **Lock to this as the lower / middle / upper beacon** (the nearest is in bold). Click roughly on it: OpenHamShack QO-100 NB spends a second looking within 500 Hz of where you clicked for the beacon's exact centre (the middle of the BPSK hump, or the midpoint of a CW beacon's two tones) and puts the correction there. A message says what it found, or that it used your click as it was. In Auto, beacon lock then searches only ±2 kHz around that place for half a minute, so it locks to your choice and not to whatever is strongest in the whole range; in Hold or Manual the correction is simply set.

### Auto, Hold and Manual

**Beacon lock** has three modes, in Settings › LNB & locks and in the badge's details:

- **Auto** - it tracks the beacon and corrects continuously. The normal choice.
- **Hold** - tracking stops and the correction stays exactly as it is, for when the beacon is fading or while you transmit if you prefer. Press **H** to hold, and **H** again to go back to Auto.
- **Manual** - nothing tracks; you set the correction. The details panel gains buttons for **−100, −10, +10, +100 Hz** and a box to type **rxCorr** (in Hz, or kHz with a k: *-27.454k*). The mouse wheel over the badge nudges it by 10 Hz, or 1 Hz with Shift. The beacon is still measured: the **Error** row says how far it now is from where you put it, so nudge until that is near zero.

In Hold and Manual nothing follows the LNB's drift - the badge says **no tracking**, and the status strip shows *rxCorr … (held)* or *(manual)* - but everything else carries on: the scopes and the dial stay corrected by the value you hold, the beacon's level is still measured, and TX lock and the level guard work as in Auto. Going back to **Auto** starts from the correction you were holding, looking ±2 kHz around it first and widening only if the beacon is not there.

Then tune. **AM** is there for listening to the beacons; everything else is described under [Modes](#modes).

### The S-meter

The **Signal** meter at the top of the **Receive** card has three styles and six units.

- **Bar**, the default: the figure at the top right, a bar beneath with a peak marker that holds for a moment and falls.
- **Analogue**: a needle meter. The scale is printed for the unit you chose (S1 to S9 then +20, +40, +60 for S-units). The section beyond S9, or above the beacon, is drawn plain while you receive - a loud station is not a danger - and turns red only while you are on the air, when what fills the passband is your own downlink. A thin amber **peak-hold needle** follows the highest recent reading and falls back after a second and a half; switch it off from the meter's menu or Settings.
- **Digital**: a large readout with a slim bar under it, and a second figure at the right (dBm beside S-units, the S reading beside dBm, the dBFS level beside the relative units).

![The analogue style in S-units, calibrated, reading S9+10.](screenshots/smeter-analogue.png)

**Click the meter** to go to the next style; **click the reading** (the figure at the top right, or the unit name in the digital style) to go to the next unit. **Right-click** for a menu with both, the peak-hold needle, **Calibrate…** and, once there is one, **Forget this calibration**. Your choice is remembered. The same choices are in **Settings › Radio**, under *S-meter*.

The meter rises at once and falls with a half-second time constant: the ballistics IARU Region 1 recommends for S-meters.

Units:

- **S (beacon ref)**, the default unless you have chosen another: the passband against the beacon's level, said in S-units - the middle beacon reads **S9**, and each S-unit is 6 dB, so a station 12 dB under the beacon reads S7. It needs no calibration, and another QO-100 station can check it, because they hear the same beacon. The receiver gain and the AGC do not move it: the passband level is measured before the AGC, and beacon lock measures the beacon from the same receive signal. With no beacon level yet (beacon lock still searching) it shows a dash.
- **dBFS**: the power in the receive passband against the radio's full scale.
- **S-units** (S1 to S9, then S9+10, S9+20...) and **dBm**, by IARU Region 1's recommendation: S9 is **−73 dBm below 30 MHz** and **−93 dBm from 30 MHz up**, and one S-unit is 6 dB. (OpenHamShack QO-100 NB's dial is the 10 GHz downlink, so it always uses −93 dBm.)
- **dB over noise**: the passband against the noise that would be in it with no signal, estimated from the zoom scope's spectrum (the same floor the *SNR in passband* meter uses). 0 means only noise.
- **dB vs beacon**: the same comparison as S (beacon ref), in dB - 0 is the beacon's level. With no beacon level yet it shows a dash.

#### Calibrating the S-meter

The radio reports levels in dBFS; turning that into dBm needs an offset that depends on the radio, its gain and your LNB. Until there is one that holds, **S-units and dBm carry an amber UNCAL mark**. They still move with the signal - on a nominal 0 dBFS = 0 dBm - but the numbers mean nothing yet; hover over the meter for the reason.

To calibrate: set **Receiver gain control** to **Manual** (Settings › Radio), put a signal of known level in the receive passband - best, a signal generator through a known attenuator into the antenna socket - and choose **Calibrate…** from the meter's menu (or the button in Settings › Radio). It shows the level it measures (an average of the last three seconds); type the signal's level as dBm (`-93`), an S reading (`S9`, `S9+20`) or microvolts (`5 uV`), and **Calibrate**. You can also type the offset itself in Settings › Radio.

- The calibration belongs to **this radio**; a different radio, or the same Pluto at a different address, starts uncalibrated. OpenHamShack QO-100 NB cannot tell one LNB from another: **recalibrate after changing the LNB, its supply, or the dish's cabling**.
- It remembers the receiver gain it was made at, and a later change of **Receiver gain** is allowed for, dB for dB, so you need not recalibrate after turning the gain. For the best accuracy, calibrate at the gain you use.
- With the receiver's **own AGC** on (Slow or Fast AGC) its gain moves with the signal and nobody knows it, so S-units and dBm go back to UNCAL until it is Manual again. The simulator is the exception: its AGC choices are a fixed gain.
- The figure is for the signal in the passband, as wide as the filter: a carrier from a signal generator reads its own level; a wide signal partly outside the filter reads less.

### Noise reduction

**Noise reduction** (Shift + N, or the switch beside the noise blanker on the **Receive** card) takes the steady hiss out of what you hear, between words most of all. It is the "NR2" of Thetis, piHPSDR and linHPSDR - Warren Pratt's (NR0V) noise reduction from the WDSP library, ported - and it learns the noise by itself: give it a second or so after switching on, or after tuning somewhere with a very different noise level.

- **NR strength** (under the switch, and in Settings › Audio) is how far it may pull the noise down: **0 %** leaves the audio untouched, **50 %** (the default) up to 20 dB, **100 %** up to 40 dB. Higher takes more noise out but makes weak syllables sound thinner; most signals sound best between 40 and 70 %.
- It works in **USB, LSB, CW and AM**, on what you hear. Decoders - CW, PSK, RTTY, FT8/FT4, SSTV and FreeDV - always get the audio without it, whatever the switch says: they decode better from the untouched passband. In the digital modes the speaker is untouched as well.
- It is **off by default**. Switching it fades over a twentieth of a second, so it never clicks, and it does not disturb the AGC.
- It adds **45 ms** of delay to what you hear while it is on.
- A **steady carrier** (a tune-up whistle, a beacon's unkeyed carrier) held for more than a second or two is, to a noise reduction, part of the noise floor, and fades with it. Keyed CW and speech come through.
- It is not a noise blanker: crashes and clicks are the **Noise blanker**'s (N) job, and the two work together.

### Auto-tune and best audio

Two buttons under the noise controls on the **Receive** card, for SSB voice (USB and LSB). Best audio listens to the station on the dial for **four seconds**; auto-tune looks after four and keeps listening, up to twelve, until it is sure. Each then acts once - the button reads *Listening…* meanwhile - and the line beneath says what it did, or why it did nothing.

**Auto-tune** (A, or right-click the signal on either scope and choose *Auto-tune onto the voice here*) puts the dial exactly on the other station's suppressed carrier, so the voice sounds right. Click anywhere on the station, or just below it (USB) or above it (LSB), and let it find the rest. If several stations are near, it takes the one whose voice spans the dial.

- SSB has no carrier to lock to, so it uses the voice. The spectrum shows where the station's speech starts, which is about 300 Hz from its carrier; that gets within a hundred hertz or two. Then the pitch harmonics finish the job. Voiced speech is a row of evenly spaced tones, and they sit where they should only when the dial is right. Over a few syllables at different pitches, only one setting of the dial fits them all.
- On the simulator it lands stations within 6 Hz on both sidebands, from 6 dB to 20 dB SNR (half the time within 1 Hz). It **refuses rather than guesses** when it cannot be sure: silence, a carrier, CW, beacons and data modes (PSK, FT8, RTTY, multi-tone modems - anything whose level holds steady), someone holding one long vowel, a station more than 2.5 kHz from the dial, or a capture where the first and second two seconds do not agree. It says which, as *Auto-tune refused: …*. If the station paused, press again while they talk.
- When it refused because it was **unsure** - two settings a pitch apart fitting almost equally, or the parts of what it heard disagreeing - the message ends with its **best guess** (and the other setting, when there is one): *Best guess +8 Hz, or -135 Hz: press Auto-tune again to try each in turn.* The next press moves the dial there at once, without listening again; the one after tries the other; the one after that goes back where it started. Keep whichever sounds right - a voice a pitch off sounds high or low at once.
- After it **has** moved the dial, the message says how to try its next best fit: if the voice sounds wrong, press again within 30 seconds and it moves there; press once more to come back. A press later than that, or after you have tuned by hand, listens afresh.
- It moves the **dial**, so you then transmit where they are, which is how a QSO is netted. With **RIT** on, it moves RIT instead and leaves your transmit frequency alone.
- Beacon lock already corrects your own LNB, so what auto-tune corrects is the **other station's** error.
- It measures; it does not track. If the station drifts, press it again.

**Best audio** (Shift + A) measures the station on the dial and sets the receive filter, AGC, noise reduction and noise blanker for it, in one go. The line under the buttons gives what it measured and chose. The button's tooltip gives the reason for each choice. The rules are plain:

| Setting | Rule |
| --- | --- |
| Noise reduction | **Off** at 20 dB SNR and over: a strong signal has nothing to lose but the edges of its speech. Below that, on: 30 % from 12.5 dB, 50 % from 7.5 dB, 70 % under that. |
| Filter | 50 Hz below the speech heard to 100 Hz above it, within 100–2900 Hz. Under 10 dB SNR the top stops at 2500 Hz, under 6 dB at 2300 Hz, where a weak voice is only hiss. |
| AGC | **Slow** on a weak signal (under 20 dB), so the gain holds through pauses instead of lifting the noise between words. **Medium** on a strong one. **Fast** when there are impulses. |
| Noise blanker | **On** when impulses (samples over the blanker's threshold, counted on the wide signal) come twice a second or more. Otherwise off. |

SNR here is the station's speech peaks against the noise in the band it occupies, which reads a few dB higher than an average would. It is applied **once**: change anything afterwards and your setting stands until you press it again. If the station paused while it listened, or the dial is on a beacon or a data signal, it changes nothing and says so.

## Transmitting

OpenHamShack QO-100 NB **refuses** to transmit, and says why on the TX button and in a notice, when:

- the licence box is not ticked (Settings › Station), on any radio but the simulator;
- the licence in force does not give your class an amateur-satellite uplink at 2400 MHz (Settings › Licence) - a class with no 13 cm, or a licence with no satellite service there;
- the radio is not running, or is receive-only (the simulator does transmit - into itself, and nowhere else);
- any part of your signal would fall outside the transponder, on a beacon, in the AMSAT-DL broadcast slot, or in a segment that does not allow your mode, or would be wider than that segment allows (wider than 2.7 kHz anywhere). It judges both edges of the signal, not the dial: SSB dialled 100 Hz under a segment edge still puts speech into the next one;
- the mode is AM, which is receive-only;
- the transmit gain is above the ceiling;
- at 600 kS/s, the uplink cannot be reached;
- an IC-9700 is chosen as the transmitter (Settings › Transmitter): you key the radio itself (below), except NB's own digital-mode overs when CAT PTT is on.

Where the licence or class is not known yet - no callsign, a country not written into OpenHamShack, or no class
chosen - transmitting is **not** refused for it: the check cannot be made, not failed. A standing warning
appears on the transmit card instead, saying so and pointing to Settings › Licence, and it clears as soon as
you choose a class under a licence OpenHamShack knows.

The bandplan it checks against:

| Downlink (MHz) | Segment | May transmit |
| --- | --- | --- |
| 10489.500 – .505 | Lower beacon | nothing |
| 10489.505 – .540 | CW only | CW |
| 10489.540 – .580 | Narrow digimodes | digital and CW, 500 Hz at most |
| 10489.580 – .650 | Digimodes | digital and CW |
| 10489.650 – .745 | SSB only | SSB |
| 10489.745 – .755 | Middle beacon | nothing |
| 10489.755 – .850 | SSB only | SSB |
| 10489.850 – .8575 | AMSAT-DL broadcast | nothing |
| 10489.8575 – .865 | Emergency (10489.860) | SSB, CW, digital |
| 10489.865 – .990 | Mixed modes, contests | SSB, CW, digital |
| 10489.990 – .997 | Multimedia beacon | nothing |
| 10489.997 – 10490.000 | Upper beacon | nothing |

FreeDV and SSTV count as digital: AMSAT-DL's SSB-only segments mean analogue speech.

### Keying

**Space** or the **TX** button transmits in USB, LSB, FreeDV and CW. In **Hold to talk** (the default) you transmit while it is held; in **Toggle** (Settings › Station) one press keys and the next unkeys. In CW, Space sends a steady carrier at your CW pitch, for tuning up; the keyer sends what you type. FT8, FT4, Q65, JS8, PSK, RTTY, SSTV and HSmodem send from their own panel.

Off the air, the TX button says in a few words how this mode transmits: *Space to talk* (voice), *Enable TX below* (FT8, FT4, Q65, JS8), *Type, Enter sends* (CW, PSK, RTTY), *Send from the panel* (SSTV, HSmodem) or *Receive only* (AM). When a key-up would be refused it says why instead, as briefly - *Not in this segment*, *Too near a beacon*, *Signal too wide* - with the whole sentence when you hover over it. Two states lock it with a padlock and change more of the window: *Set up to transmit* (a real radio and the licence box unticked: Settings › Station fixes it) and *Receive only* (a run started receive-only, or a receive-only SDR). In both the Transmit card shrinks to one line. In a receive-only run the QSO card's **Halt TX** is also hidden while nothing is on the air, and the control pad's HALT key is dimmed - but it still halts. **Halt TX** is otherwise a plain button that turns red while Enable TX is on or anything is on the air. **ARMED** with *next over in N s* means a timed over is waiting; nothing is on the air yet, and a click, Esc or Halt TX stops it.

**Esc always stops**: it unkeys at once and throws away anything queued to send, and stops a voice memory's CQ loop ([Voice memories](#voice-memories)).

While transmitting, the TX button reads **ON AIR**, with the time on air, the time left before the time-out and a bar counting down; a red glow frames the whole window; and the readout turns red.

A transmission stops by itself:

| After | Default | Set in |
| --- | --- | --- |
| The **transmit time-out** | 5 minutes | Settings › Transmit & safety |
| **Dead air**: USB, LSB or FreeDV with no sound from the microphone | 3 seconds | same |
| The **watchdog**: the window stopped responding (hung, or crashed) | 2 seconds | same |
| The radio stopping or being unplugged | at once | - |
| Moving the dial (or split, XIT, mode, transmit filter) so that the signal would be refused | at once | - |

**Power.** **Power (TX gain)** on the rail is the Pluto's transmit gain, -60 to 0 dB. The amber mark on it is the **TX gain ceiling** from Settings › Transmit & safety (-10 dB by default); nothing on the main window can go past it, and lowering the ceiling takes the power down with it. Start low - the Pluto's bare output is a few milliwatts, but your amplifier is not.

### TX lock and the landed marker

When you key, OpenHamShack QO-100 NB looks for your own signal in your downlink, a quarter of a second later. It knows exactly what it sent, so it can find it even among other stations, and measures how far from the dial it landed. That error is your Pluto's crystal, multiplied up to 2.4 GHz.

The bandscope shows a **LANDED** flag where your signal came down. **TX · own signal** reads **SEARCHING** while it looks, **LANDED** with the error once it has found you off the dial (the correction is already being applied), then **LOCKED** with what is left; the correction (**txCorr**, also shown in parts per million) is applied smoothly while you are still talking, and kept for next time, so later overs start on frequency. On the simulator, with a 2.9 kHz error, it is locked within about four seconds of the first key-up:

![On air on the simulator: TX lock found the signal 2.9 kHz low and has corrected it; it now lands on the dial (TX LOCKED +1 Hz).](screenshots/transmitting-txlock-1920.png)

The very first time, the search is wide (the whole band, if the signal is not near where it should be - a notice says so). Once TX lock has found you once, later searches are narrow.

### Staying under the beacon

QO-100's one hard rule: no signal stronger than the beacon. **Own signal vs beacon** on the rail measures it while you transmit, in dB against the beacon's level: green is comfortably below, the amber mark is your margin (6 dB by default), the purple **BEACON** line is the limit. Once you are clearly over the beacon - half a dB or more - the Transmit card says, in amber under the power slider, *Your downlink is … dB above the beacon - reduce power*, and keeps the figure current. It goes once you are back under the beacon, so a level hovering about the line does not flicker it on and off; if the over ends while you are still above, it stays as *Your last over reached … dB above the beacon* until you key again.

**Level guard**, Settings › Transmit & safety:

- **Limit** (the default) turns the transmit gain down whenever you are less than the margin below the beacon, and says so in the Transmit card's warning line (*Transmit gain trimmed to …*).
- **Automatic** also turns it back up when you are well under, never above the ceiling.
- **Warn only** changes nothing and only warns.

The guard works from the measurement, so it acts a second or so into an over, not before it. It is a help; keeping under the beacon is still your licence condition.

### Transmitting with an IC-9700

If you transmit with an **Icom IC-9700** into an upconverter to 13 cm, and receive with OpenHamShack QO-100 NB, NB can treat the 9700 as its transmitter. **For voice NB never keys the 9700**: you transmit with the radio's own PTT, as always, and NB's TX button stays locked. For NB's own digital modes - FT8, FT4, PSK, RTTY and CW lines - you can let NB key it by CAT, as WSJT-X does (step 8 below); that is off until you turn it on. What NB does:

- puts the 9700 on the frequency that lands where NB's dial says, and follows the 9700 when you turn its knob;
- shows on the bandscope where you are aimed (the TX marker) and, while you transmit, where your signal really came down (**LANDED**);
- corrects the 9700 so you land where you aim, **between overs** (see step 6);
- measures **Own signal vs beacon** while you transmit - it never changes the 9700's power; set that on the radio;
- mutes its receive audio while you transmit, so your microphone does not hear your own downlink from the speaker.

**1. On the radio.** Put the **23 cm** band on **MAIN**, and leave satellite mode off. The CI-V settings can stay at Icom's defaults: CI-V Address **A2**, CI-V USB Baud Rate **Auto**, CI-V USB Port **Unlink from [REMOTE]**, CI-V Transceive **ON** (NB works with it off too). Connect the radio's USB socket to the computer. On Windows, install Icom's USB driver first; the radio then appears as two COM ports.

**2. Settings › Transmitter.** Choose **IC-9700 (CI-V)**. Press **Find** and pick the radio's port (on Windows, if two are listed, try each with the next button); on Linux it is usually `/dev/ttyUSB0`, and your user must be in the `dialout` group (`sudo adduser $USER dialout`, then log in again). Press **Test connection**: it reads the radio's frequency once and shows it, *IC-9700 answered: 1296.200000 MHz*. It sends nothing else.

**3. The upconverter.** In **Settings › Converters**, add your upconverter to the list ([Converters](#converters)) - or press **+ QO-100**, which has DXPatrol's MK4 (1104 MHz LO for a 1296 MHz IF) and F1OPA's for 144 and 432 MHz - and choose it as the **IC-9700's upconverter**. Its offset is the **local oscillator**, from its manual or label: NB will not guess it, and refuses to save the IC-9700 as the transmitter without one. Most are **not inverted** (IF + LO = uplink); tick **Inverted** for a high-side one (LO - IF), whose spectrum is mirrored - the radio's USB goes up as LSB and its knob runs backwards - and NB converts for you. Back on **Settings › Transmitter**, **IC-9700 band**: 23 cm. If the LO puts the 9700 outside its band, Save says so, with the numbers.

Instead of CI-V you can use **Hamlib rigctld**, which lets a logger or WSJT-X share the radio: start it with `rigctld -m 3081 -r COM5 -s 115200` (3081 is Hamlib's IC-9700; use your port), choose **Hamlib rigctld**, host `127.0.0.1`, port `4532`. On Windows, Hamlib is a separate download (docs/INSTALL.md).

**4. Tuning.** Tune NB as usual: the 9700 follows, and the readout's second line shows **9700** and the frequency the radio's own display should read. Turn the 9700's knob and NB's dial follows - receive and transmit together, like one transceiver. With **Receive dial follows the radio's knob** off, the knob moves only the transmit dial (split). NB's mode follows the radio's USB, LSB or CW; set NB to FT8 or another digital mode to decode, and it stays there. If the radio is in **FM** - left there from a repeater or a local net - NB switches it to SSB (USB on air; LSB on the radio through an inverting upconverter) and says so; FM goes nowhere on the narrowband transponder. It never does this while you transmit: the switch waits for the end of the over. This is the one thing NB changes on the radio besides its frequency; turn **Switch the radio from FM to SSB** off and NB leaves the mode alone and only warns. The transmit card shows the radio: *IC-9700 1296.200000 MHz USB RX*.

**5. Transmitting.** Key the radio. NB's TX band on the scope fills red, the card reads **TX**, receive audio mutes, and **Own signal vs beacon** shows your level. If the radio is aimed where NB would refuse to transmit itself - a beacon, the wrong segment for your mode, off the transponder - the card says so in red *before* you key, and if you key there anyway its warning line says, in red, that the radio is transmitting where NB would not, until you release PTT. That is advice: **NB cannot stop the radio transmitting**. Release PTT.

**6. TX lock.** The 9700's reference and the upconverter's LO are never exact, so your signal lands off the dial. To measure it, switch the radio to **CW** and key a **steady carrier for three or four seconds**. The scope shows *LANDED +730 Hz* (say); when you unkey, NB moves the 9700 by exactly that much and says *corrected for the next over*. Key again: you land on the dial, *TX LOCKED*. The correction (**rigTxCorr** in the status strip, separate from the Pluto's txCorr) is kept for next time; a check carrier now and then keeps it fresh. With **CAT PTT** on, NB's own digital overs (FT8, FT4, PSK, RTTY and CW lines) do the same with no carrier: NB knows the audio it sent, so it finds your FT8 tones wherever your TX offset put them, shows *LANDED*, corrects the 9700 when the over ends (by at most 2 kHz an over), and the next over reads *TX LOCKED*. NB corrects only between overs, never while you are transmitting (nobody documents whether the 9700 accepts a new frequency mid-over), and only from a CW carrier or its own CAT overs: in SSB, LANDED shows roughly where your speech went (to a couple of hundred hertz) but is never used to correct, and a digital mode sent by another program with the radio's own PTT shows only your level. Three safeguards: NB corrects only while beacon lock is in **Auto**, locked on a beacon, and has been steady for 30 s with nobody changing the receive side (an LNB still drifting or a correction typed by hand would otherwise be taken for a transmit error); after each correction the next over must show the radio's own error unchanged - if the signal TX lock finds did not move with the radio, NB puts the last correction back, says *TX lock stopped correcting the IC-9700*, and corrects nothing more until you switch TX lock off and on; and the correction never exceeds **Largest TX lock correction** (Settings › Transmitter, 1000 Hz by default; a few hundred is plenty for a GPS-locked radio and upconverter) - a larger error is shown, not corrected, and a stored correction beyond it is reset to 0 at start.

**7. Receive audio** while the radio transmits, Settings › Transmitter: **Mute** (the default), **Lower** by a set amount, or **Keep playing** if you like to hear your own downlink. Only the sound changes; the scopes, beacon lock, TX lock and the level meter carry on. Your own Mute button is left as you set it. Measured against the emulated radio at the default 100 ms poll interval: audio mutes 50-120 ms after you press PTT - before your own downlink can come back, about 250 ms later - and returns about 0.65 s after you release (the round trip plus 0.3 s, so the tail of your own signal is not heard). A real radio adds its own CI-V answer time, not yet measured. A shorter **Poll interval** mutes sooner. If the link to the radio is lost while you transmit, NB stops muting within about 1.5 s and says the link was lost.

**8. Digital modes by CAT (CAT PTT).** Off by default. With **Key the IC-9700 for digital modes (CAT PTT)** on (Settings › Transmitter, *Digital modes by CAT*), NB keys the 9700 itself for its own digital-mode overs - **Enable TX** in FT8 and FT4, and the lines you send in PSK, RTTY and CW - and sends the audio to the radio's own USB sound device. It never keys it for voice: PTT and voice memories stay on the radio's PTT. What to set:

- **On the radio:** SET › Connectors › MOD Input › **DATA MOD = USB** (NB reads it, and will not key the radio while it is MIC, ACC or LAN; MIC,USB works, but your microphone is live too). **USB MOD Level** (same menu) can stay at 50 %. Do not set it by the ALC: in USB-D the 9700's ALC meter reads with any audio at all, and higher the lower RF POWER is, because the ALC is how the radio holds its power to the setting. CI-V USB Echo Back and CI-V Transceive can stay as they are.
- **IC-9700 sound device:** the radio's USB audio output, usually *USB Audio CODEC*. NB never falls back to the system default: with none chosen, or the radio unplugged, it will not key.
- **Digital audio level** (-10 dB by default) and the radio's USB MOD Level together set the drive. The right level is where the radio's power (its Po meter) stops rising as you raise it; more makes splatter, not power. Watch **Own signal vs beacon**. To set it by hand: into a dummy load, with RF POWER where you use it, send a **Tune** carrier or an FT8 over and raise the level until Po stops climbing, then leave it there. At a very low RF POWER (driving an upconverter) Po may be flat from NB's lowest level up: any level then gives the same power, and the lower one is the cleaner.
- **Delay before audio** (100 ms): NB keys the radio, waits this long for the 9700, its PA and the upconverter's relays to switch, then starts the audio. FT8 is keyed this much early, so it still starts on time. **Tail before unkeying** (50 ms) waits after the last of the audio before unkeying.

**The IC-9700 setup assistant** does most of that for you: **IC-9700 setup…** under *Digital modes by CAT* opens a window with three steps, each run only when you press its button.

1. **Find** asks the radio on the CI-V port for its ID - at A2 first, at each baud rate the 9700 offers (19200 too), then every other address - and looks for its *USB Audio CODEC* among the sound devices (Windows, Linux and macOS each name it differently; NB knows all three, and a name Windows has cut short). It fills the CI-V address, the baud rate and the IC-9700 sound device into Settings; **Save** keeps them. It sends nothing but reads. Every Icom with a USB port has a *USB Audio CODEC*, so with two radios there are two: NB then chooses the one on the same USB hub as the radio's CI-V port (Linux and Windows), and if it cannot tell, it chooses neither and says so. Then tick the dummy load and press **Which sound device?…** in step 3: NB keys the 9700 briefly once per CODEC, with a tone into each, and chooses the one that makes power (switch any other radio's VOX off first).
2. **Check** reads DATA MOD, USB MOD Level, satellite mode, which band is on MAIN and which band is selected, and lists each as *now → will be*, ticked where it would change: DATA MOD to USB, satellite mode off, 23 cm onto MAIN (by exchanging MAIN and SUB) and MAIN selected. The USB MOD Level is only on the list if it is at an extreme (below 20 % or above 80 %), to 50 %. Untick anything you want left; **Apply…** asks once, listing exactly what will change, and refuses while the radio is transmitting. NB keeps what it changed, as it was, and **Restore the radio as it was** puts exactly that back - after a restart of NB too.
3. **Set audio level** transmits, so it stays greyed out until you tick that the radio is into a **dummy load**. It needs CAT PTT on and saved and a digital mode chosen; if either is missing the window says so and offers **Turn on CAT PTT and save…** (after saying what NB will then do with the radio) and **Choose FT8**. It sends a steady tone the way an FT8 over goes, for six seconds at most, raising NB's **digital audio level** six decibels at a time from -40 dB and reading the radio's power (Po) and ALC meters; when the power stops rising it stops and keeps the lowest level that made nearly all of it. **Stop**, Halt TX or Escape ends it at once and changes nothing. It adjusts NB's level, not the radio's: if the radio's USB MOD Level is at an extreme, it says so, and Check offers to set it to 50 %. If the power is already flat at -40 dB (a low RF POWER), it says so and leaves your level alone. When it sets no level it lists its readings, which are also in NB's log, to send us.

**IC-9700 diagnostic…**, beside it, writes a report to send us when something does not work: **Run checks** reads the serial ports, which one answers, the radio's settings (DATA MOD, USB MOD Level, RF POWER, satellite mode, MAIN and SUB), how quickly it answers, the sound devices and NB's own rig settings, and never transmits. **Run keyed checks…** (dummy load ticked, then confirmed again with the band and power named) sends four short overs of a tone at the band and power the radio is set to, reads Po and ALC at each level and times the key-up and unkey; it changes no setting on the radio. **Copy report** and **Save report…** (Documents by default) get it out. The report holds no callsign, locator or serial number. Without the window: `openhamshack-nb --rig-diagnostic [file]` (add `--keyed --i-have-a-dummy-load-and-operator-present` for the keyed part; `--keyed` alone is refused).

Choosing FT8 (or any of those modes) puts the radio in **USB-D** (LSB-D through an inverting upconverter); going back to USB or LSB in NB puts it back in plain SSB. If you change the mode on the radio between overs NB leaves it, and puts it back in USB-D just before it next keys, saying so. Every over passes every check NB makes on its own transmitter - your licence, the band plan and the beacons for the band the message really occupies - and the radio's: answering, on the transmit frequency, and taking its audio from USB. **Halt TX**, Escape, switching **Enable TX** off, changing mode or turning CAT PTT off unkeys it at once; so do the transmit time-out and the watchdog, and closing NB. NB reads the radio's transmit state back after keying and after unkeying, and says so if the radio disagrees. If the link to the radio is lost mid-over, NB stops at once and says it **cannot confirm the radio stopped transmitting** - check the radio - and sends the unkey again as soon as the radio answers. The transmit card shows *TX (CAT)* while NB has it keyed.

**What a real IC-9700 still has to confirm.** One has been used on air (07/10/2026, Windows, an IC-9700 into a DXPatrol MK4): CI-V answered as Icom documents, NB tuned the radio with 23 cm on MAIN, and the signal landed on frequency. Still to confirm: that a CW carrier comes out on the displayed frequency (TX lock relies on it); how the 9700 behaves with 23 cm on SUB; the radio's own CI-V delay; that the radio accepts NB's switch from FM to SSB; and everything CAT PTT does on a real radio - keying and unkeying by CI-V, USB-D by `1A 06`, reading DATA MOD, the delay and tail, and the audio level through the USB CODEC - and the setup assistant's reads and writes (the transceiver ID, satellite mode, exchanging MAIN and SUB, the menu writes) and its level set against the radio's real ALC meter. docs/ic9700-research.md lists each with its source.

## Converters

The LNB, and any upconverter between a transmitter and 2400 MHz, are entries in **Settings › Converters**, a list like SDR Console's Converter Definitions. Each has a **Title**, a **Type** - **Down** when the radio sits below the air frequency (an LNB), **Up** when above - a **Use**: **RX only**, **TX only** or **RX/TX**, an **RX offset** and a **TX offset** (shown in Hz, typed in MHz), **Inverted** for a high-side local oscillator, and the **Most drive** its input takes. **TX only** is for a converter you only transmit through - an uplink upconverter, with something else receiving: its RX offset is greyed out and its TX offset is required. It is named by what it does on transmit, so an upconverter fed from 1296 MHz to reach 2400 MHz shows as an **Up-converter** (an RX or RX/TX converter with the radio below the air is a Down-converter, as an LNB or a transverter is called). A TX only converter is offered for the two transmit choices below and never as the LNB. The edit form shows what it does as you type: *10489.5-10490 MHz on air appears at 739.5-740 MHz on the radio*.

**Add**, **Copy**, **Edit** (or double-click), **Delete** and **Up**/**Down** work on the selected entry; one in use cannot be deleted. **+ QO-100** adds the usual LNBs (9750, 9750.1 and 9750.225 MHz, the last two SDR Console's) and three uplink upconverters (TX only); **+ VHF/UHF/SHF** adds common transverters. Neither touches your own entries. Where each value comes from is in docs/converters.md.

Under the list, **In use** chooses three:

- **LNB** - what the receiver works through. 9750 MHz for a standard LNB, 25 MHz-reference or 27 MHz (the 27 MHz Octagon is a 9750 MHz LNB too). Beacon lock measures its error, so you do not need it exactly. It must be a down-converter that does not invert.
- **Pluto's upconverter** - usually **None**: the Pluto transmits on 2400 MHz itself. If your Pluto drives an upconverter from a lower frequency, choose it here (TX only or RX/TX); NB then tunes the Pluto to that frequency and keeps its gain under the converter's **Most drive** (the Pluto gives about +6.5 dBm at 0 dB).
- **IC-9700's upconverter** - above.

The transponder's own 8089.5 MHz is not a converter: NB applies it itself. (SDR Console's QO-100 entries list it as a TX offset; NB's do not.) Settings from before this list existed - the LNB local oscillator, the upconverter's LO and mixing side - are turned into entries the first time this version starts, and everything is tuned exactly as before.

## Modes

Choose a mode on the rail's Mode card, with Ctrl + a number, or from the **Ctrl + E** menu, which has every mode (see [Keyboard shortcuts](#keyboard-shortcuts)). The **Operate** panel underneath changes with it, and the window changes to the mode's workspace unless you chose one yourself ([Workspaces](#workspaces)). Picking FT8, FT4, Q65, FreeDV or CW also tunes to its usual QO-100 frequency, unless the dial is already there - **Tune to usual frequency on mode** (Settings › Station) turns this off.

### USB, LSB and AM

The **Microphone** card: **Mic gain**, **Compressor** (0 is off), the microphone level while you transmit (peaks in the amber, never the red), and **Monitor** to hear yourself, with its level. **Transmit audio** sets the low and high edges of what you send, on a ruler against QO-100's 2.7 kHz limit; anything wider is refused. In the **Receive** card on the rail, **Filter low / high** set what you hear; you can also drag the passband's edges on the zoom scope. The SSB segments are 10489.650-.745 and .755-.850; the memories *SSB lower* and *SSB upper* go there.

**AM** is for listening to the beacons; it does not transmit.

### Voice memories

Up to six recorded messages - a CQ, a contest exchange, "QRZ?" - sent with **F1** to **F6** in USB, LSB and FreeDV, or with their buttons in the **Voice keyer** row of the Operate panel. **Radio › Voice memories…** (or **Edit…** on the row, or a right-click on a button) names them, records them and imports them:

![Radio › Voice memories…: six slots, recorded or imported, named, played to the speaker.](screenshots/voice-memories.png)

- **Record** records from your microphone - the one in Settings › Audio, through the radio's own sound stream, so it is what your PTT would send - with the level meter above; **Stop** ends it (it stops by itself after two minutes, or when you transmit). Set your **Mic gain** first and record at the level you speak at: what is kept is the microphone itself, before mic gain and the compressor, so your mic gain still applies when it is sent.
- **Play** plays it to your speaker. It does **not** transmit.
- **Import WAV…** takes a WAV file from anywhere (16-bit PCM is safest; any rate, stereo is mixed to mono), up to two minutes.
- **Clear** empties the slot. The name field is what the button and the transmit card call it.

Sending one keys exactly as your PTT would and goes through the same microphone chain - mic gain, compressor, transmit filter - and **every transmit check**: the band plan (not on a beacon, inside the SSB segments), the 2.7 kHz limit, the TX gain ceiling, the level guard against the beacon, and the IC-9700 rule (with the IC-9700 as transmitter, key it on the radio). A memory that would be refused is refused with the same sentence as PTT. The transmit card says **Sending voice memory 2: CQ contest** while it goes, and the over ends by itself at the end of the recording. A memory longer than the transmit time-out is refused before it starts. Dead air does not apply to it (it ends by itself); the time-out and the watchdog do.

**Repeat** on the row sends it again and again - a CQ loop - with the pause between calls set in the editor (10 s by default; the transmit card counts it down). **Any PTT press, Esc, tuning (a click on a scope, a memory, a band or mode change) or turning Repeat off stops it**; so does any refusal or emergency unkey. Repeat is never remembered: OpenHamShack QO-100 NB always starts with it off.

The recordings are kept as `keyer/voice-1.wav` … `voice-6.wav` in the data folder (`~/.local/share/openhamshack-nb/keyer/` on Linux, `%APPDATA%\openhamshack-nb\data\keyer\` on Windows; names in `keyer/voice.json`), so you can copy them to another computer.

### CW

Type in the line under the terminal and press **Enter**: the keyer sends it at **Speed** (5-50 wpm), at your **Pitch**. **As you type** sends each word as you finish it instead of the whole line. Typing while one is being sent queues the next; **Stop** (or Esc) empties the queue and unkeys. **Filter** narrows what you hear (, and . on the keyboard narrow and widen it too). The decoder writes what it reads into the terminal and on the waterfall, and says the speed it hears; a pattern it cannot read is shown faintly in brackets.

The **QSO** fields - their call and the report (599) - fill in the macros, your CW memories. The macro buttons send `{MYCALL}`, `{CALL}` (or `{DXCALL}`, the same: their call), `{RST}` and `{LOC}` (your locator) filled in; **F1** to **F8** send them from the keyboard, even while you are typing in the line, as long as the Operate panel is showing. A macro whose field is empty - `{CALL}` with no call typed, `{LOC}` with no locator in Settings › Station - is not sent, and says what to fill in. **Edit** changes them (one per line, up to eight). Click a CW signal on a scope to put it at your pitch.

### PSK31, PSK63, PSK125 and RTTY

The same terminal, typing line, queue and macros as CW. The decoder listens at 1000 Hz in the audio; **Signals**, on the right, lists the carriers in your passband once a second, and clicking one tunes it onto the decoder (it is marked **◀ decoding**). Clicking a signal on a scope does the same. RTTY is 45.45 baud, 170 Hz shift. Decoded text also appears on the waterfall beside the signal. On noise the RTTY decoder prints stray characters, as any RTTY decoder does.

![RTTY on the simulator: the terminal, macros, and the signal list.](screenshots/main-rtty-1920.png)

### FT8, FT4 and Q65

Decoding uses OpenHamShack QO-100 NB's own decoder, a port of WSJT-X 2.7.0's `jt9` that found exactly what `jt9` found on hours of real QO-100 slots; where it is missing (the `all` package) or fails, WSJT-X's `jt9` decodes instead if WSJT-X is installed, and where both are there `jt9` checks every slot. No package carries WSJT-X: on Windows and macOS it is used only if you install it yourself, and nothing is missing without it. The panel says which is decoding (*decoder: ohsdigi* or *jt9*, under band activity); **Settings › Station › FT8 and FT4 decoder** can put `jt9` first. Each 15-second FT8 slot (7.5 s for FT4) is decoded 13.5 seconds in, so a reply can go in the next slot. Sending uses OpenHamShack QO-100 NB's own encoder, a port of WSJT-X 2.7.0's that makes the same signal bit for bit (the `all` package uses WSJT-X's `ft8code`/`ft4code` instead). A message WSJT-X could not send - a report of +99, say, or two nonstandard calls with neither in `<>` - is refused with a sentence saying why, rather than sent as noise.

These modes bring the **Digital** workspace, where the band activity takes most of the window: the wide scope shrinks to a strip and the zoom scope narrows. Drag the dividers as you like; the workspace remembers them, separately from the other workspaces. **Ctrl and the mouse wheel** (or **Ctrl +** / **Ctrl -**) over the list make its text larger or smaller (16 px to start with), and the size is kept.

**Q65** (Q65-60A) works like FT8, with the same messages, QSO card and sequencing, over **60-second** periods: the slot clock goes round once a minute, the first line of the panel says *Q65 · 60 s periods*, and each period is decoded once, 55 seconds in. Its receive and transmit marks on the zoom scope are 108 Hz wide, the signal's width. Q65's averaging over several periods is not offered.

- **The pile-up line**, above the band activity when there is a pile-up, answers the three questions a pile-up asks: who it is on (the station in your DX call, or else the one with the most callers over the last two slots of one period, at least two), how many are calling and the strongest few with their reports (*+N more*), and where you stand - *you: not calling*, *you: calling*, *you: heard here* (your own call to them came back through the satellite, so your signal reached the transponder), or *answered you*; and *working …* when they answered someone else. Click it to put that station in the DX call; nothing is sent, and not while Enable TX is on.
- **Band activity** lists the decodes, slot by slot: UTC (as 15:38:45), SNR, time offset, audio frequency, message and the sending station's **country**, by its short name (hover for the full name, its continent and prefix). CQs are highlighted, messages to you in gold, and stations already in your log are ticked and greyed. Your own overs are in gold too: red is kept for being on the air.
  Countries come from `cty.dat`, AD1C's country file, which OpenHamShack QO-100 NB carries - no WSJT-X needed; each release has the edition current when it was made. A portable call counts where it is operating (EA8/G4ABC is the Canary Islands, G4ABC/MM is none). AD1C reissues the file every few weeks as DXpeditions come and go: to use a newer one from [country-files.com](https://www.country-files.com/) (the *Big CTY* edition, as WSJT-X uses), put its `cty.dat` in OpenHamShack QO-100 NB's data folder, and it is used instead of the built-in one; the program's log names the file in use (`cty.dat:`) each time it starts.
- **Click a line** to answer that station: the DX call and grid are filled in, Tx1 is chosen, your period is set opposite to theirs, your receive offset goes to theirs (and your transmit offset too, unless **Hold TX freq** is on), and **Enable TX** turns on. The call goes out in your very next slot - in the one you are in, if it is yours and you clicked in its first 6 seconds. Up to 2 s in, the whole message goes, that much late; after that, as in WSJT-X, it starts at once from the point a punctual one would have reached, the start dropped. The station you call still decodes that, knowing its own call, up to about 6 s; a station decoding blind, up to about 4.5 s. Anything still waiting to go for your last QSO - an RR73 repeat, say - is dropped.
- **The slot clock** counts down the slot and says whether it is EVEN or ODD, RX or TX, and **TX NEXT** when you will transmit in the next one. **Even / Odd** chooses your period by hand.
- **Tx1 … Tx6** are the standard messages (Tx6 is your CQ); click one to send it next.
- **Auto seq** moves through the QSO as replies arrive, as WSJT-X does, and logs it when it is complete. A reply decoded before your slot starts goes in that slot; one that arrives after your transmission has begun goes in your next. **Log QSO** logs it by hand; **Clear** starts afresh; **Halt TX** stops at once. The Tx row chosen next is outlined in the accent colour, and turns red only while that over is armed or on the air.
- **Hold TX freq**: answering a station moves only your receive offset, not your transmit one.
- **TX = RX** puts your transmit offset on your receive offset and keeps them together while it is on: a click on a station, or on either marker in the zoom scope, moves both. (Hold TX freq is greyed while it is on.)
- On the zoom scope, **click** inside the audio window to set the receive offset (and the transmit one, unless Hold TX freq is on); **Shift + click** sets only the transmit offset. Both are drawn there.

The FT8 memory is 10489.540 (the narrow digimode segment); the contest one 10489.870.

![FT8 on the simulator, in the Digital workspace: band activity with each sender's country, and a CQ answered - the DX call filled in and Tx1 on the air.](screenshots/main-ft8-1920.png)

### JS8

JS8 is JS8Call's mode: free text typed to a station, sent as a run of frames, one per period. The panel has its own **JS8 band activity** - UTC, dB, DT, Freq, Speed, From and Text - where each message's frames are joined back into one row, growing as they arrive, as JS8Call shows them. **Only to me** shows just the messages to your callsign; **Heartbeats** shows or hides the automatic *@HB* heartbeats stations send while they listen. All five JS8 speeds (Slow 30 s, Normal 15 s, Fast 10 s, Turbo 6 s, Ultra 4 s) are decoded at once.

To send: type a callsign and text, or *CQ*, in the **Send** card, or use **CQ**, **Heartbeat**, or **Reply** (a message to the station picked in the list), then **Send**. That queues the message and turns **Enable TX** on: its frames go out one per period from the next period, at the speed chosen on the speed buttons (Normal unless you choose another; not changeable while a message is going out), and the line under them says which frame is next. Each frame is an over like an FT8 one and passes every transmit check. **Enable TX** off, **Halt TX** or **Esc** stops it, cutting a frame on the air. JS8 has no QSO sequence to automate, so there are no Tx rows. It needs your callsign in Settings › Station. The JS8Call memory is 10489.548.

### Reporting what you hear to PSKReporter

[PSKReporter](https://pskreporter.info/) maps who is being heard where. OpenHamShack QO-100 NB can add what it decodes, as WSJT-X does - **off unless you turn it on**: **Settings › Station › Report stations heard to PSKReporter**. It needs your callsign and locator set on the same page, and refuses to turn on without them (every report says who heard it and where).

- **What goes**: for each station decoded in FT8, FT4, Q65 or JS8 whose message carries a callsign - its call, the frequency, mode, signal report, the slot's time and, if the message had one, its grid - with your callsign, locator and *OpenHamShack QO-100 NB* and its version. Nothing else: no audio, no log, nothing about the computer.
- **The frequency is the downlink as heard** (10489.5xx MHz), the dial plus the signal's audio offset - what WSJT-X users on QO-100 already report, so your spots sit with theirs.
- **When**: in one batch every five minutes or so, as PSKReporter asks, and each station once per five minutes. Decodes marked low-confidence (WSJT-X's `?`), calls the decoder could only show as `<...>`, and your own call are not reported. JS8 messages are reported only when they are a plain `CQ`/`DE` with a callsign; most JS8 frames are not yet unpacked.
- **Off again** drops whatever was waiting, unsent. Closing the program sends what was waiting.
- If the Internet is down the reports are simply lost; it never interrupts you to say so (the program's log notes it, once an hour).

### FreeDV

FreeDV needs `libcodec2` (on Windows it is built in). Choose **700D** (the robust one usually heard on QO-100), **700C**, **1600** or **2020**; the ones your codec2 cannot open are greyed (700E does not open on codec2 1.2). The card shows **SYNC** when the modem has locked to a signal, the modem SNR, and the text channel (usually the other station's callsign). Talk with Space or the TX button as in SSB; dead air applies. The *FreeDV activity* memory is 10489.640.

### SSTV

Received pictures paint line by line as they arrive, in Robot 36, Martin 1, Scottie 1 or PD 120, and are saved; the **Gallery** shows them, newest first, and **Open folder** opens where they are kept. Click a thumbnail to show it, double-click to open it. To send one, choose the mode under the gallery, then **Send a picture…** and pick a PNG, JPEG, BMP or GIF.

![SSTV: a Robot 36 picture arriving, and the gallery.](screenshots/main-sstv-1920.png)

### Send files with HSmodem

**HSmodem** is DJ0ABR's high-speed modem - the one the [multimedia beacon](#the-multimedia-beacon) uses - and stations use it on QO-100 to send each other pictures, text and files in a 2.7 kHz channel. OpenHamShack QO-100 NB sends and receives it the way DJ0ABR's program does, so it can work stations running HSmodem as well as other OpenHamShack QO-100 NB stations.

**Both stations must use the same speed**: HSmodem does not work out the speed it is hearing. Choose it at the top of the **Send** card; the receiver listens at that speed too. The default, **4410 bit/s QPSK**, is the one HSmodem itself starts on and calls the QO-100 standard.

| Speed (bit/s) | Modulation | Width | Needs about (SNR in 2.5 kHz) |
| --- | --- | --- | --- |
| 1200 | BPSK, 1200 Bd | 1.34 kHz | 5 dB |
| 2400 | BPSK, 2400 Bd | 2.66 kHz | 7 dB |
| 3000 | QPSK, 1500 Bd | 1.68 kHz | 9 dB |
| 4000 | QPSK, 2000 Bd | 2.23 kHz | 9 dB |
| **4410** | QPSK, 2205 Bd | 2.46 kHz | 10 dB |
| 4800 | QPSK, 2400 Bd | 2.68 kHz | 9 dB |
| 5500 | 8APSK, 1837.5 Bd | 2.07 kHz | 11 dB |
| 6000 | 8APSK, 2000 Bd | 2.25 kHz | 12 dB |
| 6600 | 8APSK, 2205 Bd | 2.48 kHz | 13 dB |
| 7200 | 8APSK, 2400 Bd | 2.69 kHz | 13 dB |

All ten fit QO-100's 2.7 kHz limit, measured as OpenHamShack QO-100 NB measures every transmission (the band holding 99.5 % of the power). The last column is where frames start to be lost, measured on OpenHamShack QO-100 NB's own signal; give yourself a few dB more. Below the beacon's level, as you must be, the QPSK speeds have a comfortable margin on a good station; the 8APSK speeds need a strong one.

**Where.** HSmodem goes in the **digimodes (2.7 kHz max)** segment, 10489.580-.650, or among the mixed modes at 10489.865-.990. It is refused in the 500 Hz narrow digimode segment and the SSB segments, as any signal that wide is. As in HSmodem, the signal is centred 1500 Hz above the dial: tune the dial 1.5 kHz below the middle of a station's signal, or click its middle on a scope and tune down 1.5 kHz. The receiver finds a station that far and somewhat more off tune by itself (about ±270 Hz at 4410, ±170 Hz at 7200).

**Receiving.** The **Received** card's top line says how it is going: **in sync** with the MER (the quality of the symbols: a few dB above the speed's figure in the table is comfortable), how far off tune the station is, and the frames decoded; **searching** when nothing is coming. A file shows its name, who is sending (from the station frame HSmodem sends: call and locator) and a bar as its blocks arrive. Everything received is listed with the time and the sender - pictures with a thumbnail - and the newest is shown: a picture, or the text of a message or text file. Click an entry to show it, double-click to open it. Received files are saved in the data folder under `hsmodem/` (**Open folder**), with names made safe; a second file of the same name is kept beside the first (`notes-2.txt`). A block lost to a fade is filled in if the station sends the file again.

![HSmodem: a station's picture and message received, and a picture of our own going out.](screenshots/main-hsmodem-1920.png)

**Sending.** In the **Send** card:

- **File…** sends any file (up to 1 MB). Text, HTML and other files are zipped first, as HSmodem does; a `.jpg` goes as a picture.
- **Picture…** takes a PNG, JPEG, BMP or GIF and makes a JPEG of it the way HSmodem's own program does: choose the **size** (640×480 down to 160×120, or as it is; the shape is kept) and the **quality** - Low, Medium, High or Very high, which is really a size limit (about 12, 22, 45 or 90 kB at 640×480: about 30 s, 1, 2 or 4 min at 4410 bit/s). The JPEG quality is lowered until the picture fits.
- Or **type a message** in the box: it goes as a text file, `message.txt`, which is how HSmodem sends text.

Under them it says what will go: the size, the number of frames and **how long it takes at the chosen speed**. That includes about six seconds at the start in which the first frame is repeated: HSmodem's preamble, which every receiver needs to lock on. Your callsign and locator go out with every file, as in HSmodem.

**Send** transmits it; the bar shows how far it has got. **Stop** (or Esc) stops at once. Sending goes through the same transmitter path as every other mode, so everything in [Transmitting](#transmitting) applies: the licence acknowledgement, the band plan, TX lock, staying under the beacon, and the transmit time-out. Two more refusals come before anything is keyed: without a callsign (Settings › Station) nothing is sent, and anything that would take longer than the transmit time-out is refused rather than cut off part-way - choose a faster speed, a smaller picture, or a longer time-out in Settings › Transmit & safety.

**How compatible.** OpenHamShack QO-100 NB's HSmodem is a port of HSmodem's own code and has been checked against it: HSmodem's transmitter and receiver, compiled from its published source with the signal-processing library it ships, sent a file to OpenHamShack QO-100 NB and received one from it at all ten speeds, every frame, clean and in noise. It has not yet worked a real HSmodem station on the air, and HSmodem's own Windows program has not been run against it (see [Not yet verified](#not-yet-verified)).

## Logbook

**Logbook** in the lower panel (Ctrl + L, or the book button in the header). FT8 QSOs log themselves (see above); everything else goes in with **Log a QSO** on the right: call, reports sent and received, name, grid and comment. The frequency, mode and time come from the radio. **Enter** in any field logs it.

Click a call to open its page on QRZ.com in your web browser (a portable call such as EA8/G4ABC/P opens G4ABC). Double-click a cell to correct it (the time, frequency and mode are fixed). **Delete** removes the selected rows. **Export ADIF** (also **File › Export log as ADIF…**) writes an `.adi` file for your logging program, LoTW or a QSL service.

![The logbook.](screenshots/logbook-1920.png)

## Sharing the logbook with a controller

The logbook and the station profile (callsign, locator, country, licence and class) are kept once per computer and shared by every OpenHamShack app on it: QO-100 NB and Radio on one laptop keep **one** log, and a contact logged in either appears in both. Logs from before this version are moved in the first time it starts; the old file is kept beside it as `log.jsonl.migrated`.

If you run an **OpenHamShack controller** on your network, **Settings › Controller** joins it: **Find controllers** lists the ones on your network (or type its address), then sign in with your controller user name and password (and the code from your authenticator app, if your account has one) and press **Pair**. From then on the logbook and station profile are kept in step with the controller and every other app paired with it, in both directions. If the two logbooks belong to different callsigns, you are asked whether to **merge** them or to **use the controller's** (this computer's is then kept as a file). The page shows how the sync is going.

Nothing needs the controller: with it switched off or out of reach the app logs exactly as before, and catches up when it is back. **Unpair** stops the sharing and keeps every contact and the profile on this computer. Your password is used once, to pair, and never stored.

## The control pad (Ajazz AKP03E)

An **Ajazz AKP03E** (USB 0300:3002: six keys with pictures, three small buttons, three knobs) works OpenHamShack QO-100 NB without the mouse: the knobs tune, set the volume and step through bands, the keys change mode, mute, record and step size. Plug it in and it is used at once; nothing needs setting up. If several OpenHamShack apps are open, the pad belongs to the one you last clicked in.

**Close the Ajazz or Mirabox "Stream Dock" software first**, including from the system tray by the clock. Windows lets both programs open the pad, and then the two fight over its keys and pictures.

**Transmitting from the pad is off until you allow it.** K1 is PTT (hold to transmit) unless you move it, but until **Settings › Control pad › The pad may transmit** is ticked and saved, the PTT key shows *PTT off* and pressing it keys nothing. When it is on, the PTT key goes through every check the TX button makes (licence, band plan, locks), and the transmitter stops at once if the pad is unplugged or the program stops answering it.

**Changing what the controls do.** **Settings › Control pad › Keys and knobs** has one row for each key (K1 to K6, top left to bottom right), each small button (B1 to B3) and each knob (D1 to D3, left to right) - turned, and pressed - with a list of what that control can do in QO-100 NB. Keys and buttons offer the presses, knobs the turns; a key can also do one step of a knob's job (*Tune up one step*, *Next memory*, *Volume down*...). **Nothing** is allowed anywhere. The pictures on the keys follow your choices. Changes take effect when you press **Save**; **Cancel** leaves the pad as it was, and **Reset to defaults** puts back the layout below. As shipped:

| Control | Does |
| --- | --- |
| K1 | PTT (hold to transmit) |
| K2 | Mute |
| K3 | Record |
| K4 | Next mode |
| K5 | Auto-tune |
| K6 | Stop transmitting |
| B1 | Next tuning step |
| B2 | Nothing |
| B3 | Next page (only useful with pages set up on a controller) |
| D1 | Volume; pressed: mute |
| D2 | Tune; pressed: next tuning step |
| D3 | Memories; pressed: nothing |

**Next mode** steps through the modes in the Mode card's order, group by group (Voice, then Digital, then Pictures & data), and brings the mode's workspace as a mode button does. While you record, the **Record** key reads *● ON* in amber, as REC does in the status strip: on the pad, too, red is only for transmitting.

Besides those, a control can be set to **Noise reduction on/off**, **Filter width** (a knob: the high edge in SSB, the width in CW and AM; the digital modes' filter is fixed), **Transmit power** (the Pluto's gain, 1 dB a detent) or **Beacon lock: Hold / Auto** (the **H** key).

**PTT** can only go on one of the six keys with a picture (the key that shows *ON AIR* while you transmit), and only on one: choosing it for another key moves it there, and K1 then does nothing until you give it something else. Set it to **Nothing** on every key and the pad cannot transmit at all; the page says so. Moving PTT never changes the rule above: it still keys only once *The pad may transmit* is on, through every check, and stops when the pad is unplugged. While you are transmitting, Save refuses to move or remove the PTT key, so the key you are holding always stops the transmission.

Your choices are kept with the station profile, so they survive updates and, with a controller paired, follow you to the controller's pad. A choice this version cannot use (an action that has gone, a setting from a newer version) puts that one control back to its default rather than doing something else.

**Settings › Control pad** says whether the pad is found and working and, if not, why, in words: another program has it, no permission (Linux), unplugged, a model this version does not drive. **Test controller** lights each key in turn; then press every key and button and turn every knob, and each one is listed on the page. Nothing reaches the radio during the test. **Copy controller report** puts a short report on the clipboard (what is plugged in, which part of it the program opens, what the installation has for it, the problems seen): paste it into an email to the developers. It holds no callsign, locator or passwords. From a terminal, `openhamshack-nb --pad-report` prints the same report without opening the window.

On Linux the `.deb` installs the udev rule that lets you open the pad without root; it takes effect at once. The AppImage cannot install it: if the page says *no permission*, run once
`echo 'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0300", ATTRS{idProduct}=="3002", MODE="0660", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/60-openhamshack-pad.rules && sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw`
and plug the pad in again.

Only the AKP03E's second revision (0300:3002) is driven. The first AKP03E (0300:1002), the AKP03 and AKP03R and Mirabox's N3 are recognised and named in the report, but not used: the first AKP03E, for one, never reports a key being let go, so a held PTT could not end.

## Memories

**Memories** in the lower panel (Ctrl + B). Click one to go to its frequency and mode; **Alt + 1** to **Alt + 9** recall the first nine from anywhere. **Save current** stores where you are, under a name; saving under an existing name replaces it. **Delete** removes your own; the built-in ones stay:

| Memory | Downlink (MHz) | Mode |
| --- | --- | --- |
| Lower beacon | 10489.4997 | CW |
| Middle beacon (PSK) | 10489.7485 | USB |
| Upper beacon | 10489.9989 | CW |
| CW segment | 10489.520 | CW |
| FT8 | 10489.540 | FT8 |
| JS8Call | 10489.548 | USB |
| FreeDV activity | 10489.640 | FreeDV |
| SSB lower | 10489.700 | USB |
| SSB upper | 10489.800 | USB |
| Emergency | 10489.860 | USB |
| Contest FT4/FT8 | 10489.870 | FT8 |

The beacons are F1A: one carrier that moves 400 Hz between a key-up tone and a key-down tone. Their memories put the key-down tone on the CW pitch (700 Hz), so the CW decoder reads the Morse and the other tone falls outside the CW filter. With the pitch changed, tune so the key-down tone (10489.5004 for the lower beacon, 10489.9996 for the upper) sits on it.

## The multimedia beacon

AMSAT-DL's **High-Speed Multimedia Beacon**, at 10 489.995 MHz just below the upper beacon, sends text and data from the ground station DK0SB in Bochum: AMSAT bulletins, DX-cluster spots, a CW skimmer's spots, and pictures of the narrowband and wideband transponders' spectra (it can send photos too). It uses DJ0ABR's HSmodem: 8APSK at 7200 bit/s in 2.7 kHz.

OpenHamShack QO-100 NB receives it **in the background, whatever you are tuned to**: the beacon is always inside the 500 kHz the receiver covers, so it is decoded from the wide signal through a channel of its own, not from what you are listening to. Nothing about it transmits. **Beacon** in the lower panel (**Ctrl + M**) shows what has arrived:

![The multimedia beacon: a bulletin, and the decode status.](screenshots/beacon-bulletins-1920.png)

- **Bulletins**: the AMSAT bulletins, newest first; click one to read it. Each comes round every few minutes.
- **DX cluster**: the spots the beacon relays, newest at the top - UTC, the DX station, its frequency, the comment, who spotted it and their locator. Spots on the QO-100 downlink are in blue; **double-click** one to tune to it. With **Spots on scope** on (top right), each new QO-100 spot is also written on the wide waterfall at its frequency, as FT8 decodes are. The box under the table is the **CW skimmer**'s spots.
- **Pictures**: thumbnails; click one to see it full size.
- **Spectra**: the narrowband and wideband transponders as the beacon measures them at the ground station - a second opinion on what your own scope shows.

![DX-cluster spots, one of them written on the wide waterfall.](screenshots/beacon-dx-1920.png)

The line under the page buttons says how the beacon is decoding: **receiving**, how far it sits from 10 489.995 MHz after beacon lock's correction, **MER** (the quality of its symbols: above 15 dB is comfortable, below about 12 dB frames start to fail), how many frames have decoded and how many came and did not, and when the last one arrived. While a file is arriving it shows its name and how many of its blocks are in. **Looking for the beacon** means nothing has decoded yet: it needs beacon lock first (until the receive correction is found the beacon is outside its channel), then a few seconds. The status strip shows **MM beacon** and its MER while it is decoding.

Everything received is saved in the data folder, under `mmbeacon/` (**Open folder**), and shown again the next time OpenHamShack QO-100 NB starts. A file that arrived with blocks missing is completed from the next time it is sent. Received file names are the sender's; any path in one is ignored.

![A picture from the beacon (the simulator's test card).](screenshots/beacon-pictures-1920.png)

It costs little: about half a per cent of one laptop core, and an estimated few per cent of a Raspberry Pi 400's. **Settings › LNB & locks › Receive the multimedia beacon** turns it off (and on again) without restarting. The simulator sends a real beacon signal with sample bulletins, spots and a test card, so all of this can be tried with no dish.

**Not yet seen on air.** The decoder is a port of HSmodem itself and gives the same frames as HSmodem's own receiver on test signals, but the real beacon has not yet been received with it: its exact filter and frequency are not published, and it may not send pictures at all. What a first on-air test should look for is in `docs/hsmodem-research.md` (section 7).

## The middle beacon's text

The middle beacon at 10 489.750 MHz - the one beacon lock follows by default - also carries text. It is 400 bit/s BPSK in the block format AMSAT designed for AO-40: DK0SB in Bochum sends four blocks, **K**, **L**, **M** and **N**, one every 25 seconds, so each comes round about every 100 seconds. On air in October 2026 they said who is sending (*HI de Qatar-OSCAR 100 (DK0SB)*), when the transponder opened, the 2020 band plan and beacon frequencies, and the emergency frequency (10 489.860 MHz down, 2400.360 MHz up). K carries only the first line.

OpenHamShack QO-100 NB decodes it **in the background, whatever you are tuned to**, as it does the multimedia beacon: through a channel of its own at the beacon, from the wide receive signal. Nothing about it transmits. **Beacon** in the lower panel (**Ctrl + M**), page **Middle beacon**, shows the latest block of each type and when it came (UTC). The line under the page buttons is then the middle beacon's:

- **receiving** - a block has decoded in the last minute. Then how far the beacon sits from 10 489.750 MHz after beacon lock's correction (a few hertz), the **SNR** of its symbols (with the beacon about 10 dB over the noise on the developer's dish it read 11-15 dB, and every block decoded), how many blocks have decoded and how many were heard starting and did not, and when the last one came.
- **beacon found, waiting for a block** - the decoder has the carrier and is waiting for the next block to start, at most 25 s.
- **looking for the middle beacon** - nothing found yet. It needs beacon lock, or a receive correction within a few hundred hertz, then a few seconds.

Each block is checked against its own CRC: a block that does not pass is never shown, only counted. One that passes after a single weak symbol was put right is shown like any other. The latest block of each type is kept in the data folder, under `midbeacon/`, and shown again the next time OpenHamShack QO-100 NB starts.

Between its text blocks DK0SB also sends AO-40 **FEC** frames, coded to survive a weaker signal; whether they carry the same text is not known. OpenHamShack QO-100 NB does not decode them yet, so on a dish that hears the beacon only just above the noise the text may not come while beacon lock still works.

It costs very little: well under one per cent of one laptop core. **Settings › LNB & locks › Decode the middle beacon's text** turns it off (and on again) without restarting. The simulator's middle beacon sends four blocks of its own text in the same format and timing, which say they are the simulator's, so the page can be tried with no dish.

## KG-STV pictures

Some stations on the transponder send pictures digitally with **KG-STV**, JJ0OBZ's program, at **10 489.6249 MHz USB**. A picture is 320 x 240, sent as 300 blocks of 16 x 16 pixels, one at a time, in about two minutes; who sent it comes with it. On 7 October 2026 four were heard in three hours, from VU2SAA, DL4CQ (twice) and DG8RP.

OpenHamShack QO-100 NB receives them **in the background, whatever you are tuned to**, the way it does the beacons: through a channel of its own at 10 489.6249, from the wide receive signal. Receiving transmits nothing (sending is below). **Beacon** in the lower panel (**Ctrl + M**), page **KG-STV**, shows the picture coming in, block by block as each arrives - a picture you tune into halfway shows the half you heard - with the sender's callsign, the mode, and how many of the 300 blocks are in. A picture is finished when the sender says so, or after 30 seconds with nothing heard. Finished pictures with at least 50 blocks are kept as PNG files in the data folder, under `kgstv/`, named by the UTC time and the callsign; they are the thumbnails beside the picture, and a click enlarges one. Text messages, which KG-STV can also send, appear under them. The line under the page buttons is then the KG-STV receiver's:

- **receiving** - a frame has decoded in the last 30 seconds: from whom, how far the signal's centre sits from where it should be after beacon lock's correction, how many frames have decoded and how many were heard starting and did not, and when the last one came.
- **listening** - nothing heard for 30 seconds.

Every block is checked against its own CRC: a block that does not pass is left out, never painted wrong, and the sender's later repeats of missed blocks fill the gaps. One that passes after a single weak bit was put right is shown like any other.

KG-STV can send in four ways: MSK or a four-level FSK, each with or without error-correcting coding. Pictures in MSK, coded or not, are proven on real ones: all four stations on 7 October used MSK, one of them coded; played back through OpenHamShack QO-100 NB, 1194 of their 1200 blocks decoded. The four-level FSK was never heard, so how the decoder reads it is a careful guess: a block it gets wrong fails its CRC and is left out, so at worst those pictures do not come. Receiving needs beacon lock, or a receive correction within a few hundred hertz; a station a few hundred hertz off is followed.

It costs about half a per cent of one core. **Settings › LNB & locks › Receive KG-STV pictures** turns it off (and on again) without restarting. The simulator has a KG-STV station of its own, OPENHAMSHACK-SIM, which sends a test card every minute and a half, so the page can be tried with no dish.

### Sending a picture

**Send picture…**, under the picture on the KG-STV page, opens a window where you choose a picture file (PNG, JPEG, BMP, GIF). It is cut to 4:3 from the middle and scaled to 320 x 240, as KG-STV itself does, and shown as the other station will receive it. Beside it:

- **Quality**: how finely the picture is coded - Finer, Standard (what every station heard on QO-100 uses), Faster, Fastest - each with how long the picture takes on the air, usually a minute and a half to three minutes. A quality longer than your transmit time-out (**Settings › Transmit & safety**, 5 minutes unless you changed it) cannot be chosen; the window starts on the finest one that fits.
- **Frequency**: KG-STV's own, 10 489.6249 MHz USB (sending retunes the transmitter there first), or wherever the transmitter is tuned now. If a KG-STV picture is coming in on that frequency, the window says so: sending would go over it.
- **Callsign line**: your callsign and locator from **Settings › Station**, sent before the picture and again after every ten blocks, as KG-STV does. Without a callsign nothing can be sent.

Nothing transmits until you press **Send**. The picture then goes out like any digital message: through the Pluto, or through an IC-9700 by CAT PTT if **Key the IC-9700 for digital modes** is on (if it is off, the IC-9700 is not keyed and NB says so). The band plan, your licence, the beacons and the level checks judge it as KG-STV, which is about 1.4 kHz wide: it is refused in the 500 Hz narrow digimode segment and allowed in the 2.7 kHz one, where KG-STV lives. The window closes and a strip above the picture follows the over - "block 120 of 300" - with a **Halt** button; **Escape** and **Halt** in the main window stop it too, at once. Changing the mode on the right also stops it. Afterwards the strip says whether all of it went. On the transponder you will usually see your own picture come back on this page as it goes out.

## The band skimmer

OpenHamShack QO-100 NB keeps a list of **every signal on the transponder**, found in the background from the wide receive signal whatever you are tuned to, and says what each one is. **Band** in the lower panel (**Ctrl + K**) shows it, one row per signal in frequency order; the same signals are marked along the bottom of the wide scope. Nothing about it transmits.

- **SSB** voices, with their **dial** - the other station's suppressed carrier - measured by auto-tune ([Auto-tune and best audio](#auto-tune-and-best-audio)), the same measurement as the button's. A dial is shown to the hertz only once **two separate listens agree** to within 10 Hz: on real QO-100 voices one listen's answer is a pitch or so off too often to be shown as the dial. Until then the row says *SSB?* with **~** before the frequency: either where one listen put the carrier (to the hertz, waiting for a second to agree) or, before any listen has answered, where the voice's spectrum puts it (to a hundred hertz or two). The note says why a voice has no dial yet, in auto-tune's own words.
- **CW** (a keyed signal), **Carrier** (a steady line), **Data** (a steady signal: PSK, RTTY, a modem - or one auto-tune says is not a voice).
- **The beacons** and AMSAT-DL's broadcast slot, by the band plan.
- **FT8**, **FT4/FT8 (contest)**, **Q65** and **JS8**: one row for each calling window, with how many signals are in it - and, when your own decoder is running there, the calls it has heard in the last two minutes.
- Known signals, by where they are (from a 3-hour recording, listed in the project's notes): **KG-STV picture** at 10 489.626 (its USB dial 10 489.6249; NB receives these pictures itself, see [KG-STV pictures](#kg-stv-pictures)), and three it does not decode: the **ARQ data link** at 10 489.637, the **unidentified multicarrier** that starts on the hour at 10 489.646, and the **burst every ten minutes** at 10 489.597. These names are only right once beacon lock is, as every frequency on the scope is.

**Click a row to tune there**, in its mode: a measured SSB dial exactly; a voice without one to where it is thought to be, and auto-tune then listens there as a right-click's *Auto-tune onto the voice here* does; CW, data and beacons as a click on the scope at them would; a calling window to its calling frequency in its mode. A **click on a mark** on the wide scope does the same, and hovering over one says what it is. The buttons over the list show **All**, **Voice**, **CW**, **Data** or **Other**; **Marks on scope** turns the marks off. Rows heard in the last 20 seconds are bright; quieter ones (a QSO between overs) are grey, and go after two minutes.

**It uses a share of the processor you choose.** Listening to a voice to measure its dial is the costly part, so the skimmer is given a budget - **Settings › LNB & locks › Band skimmer's share of the CPU**, 10 % of one core by default - and listens to one more voice only while it has budget left. A slower computer, or a smaller share, means dials are measured more slowly, never that receiving suffers; finding and naming signals costs little and goes on regardless. The line over the list says how many signals are listed, how many dials are measured, how many listens it made in the last minute and what it is using. **Settings › LNB & locks › Skim the whole band** turns it off.

The **Watch** workspace opens on this list, with two thirds of the window for the wide scope ([Workspaces](#workspaces)), and a right-click on a signal on either scope reads the same list to say what it is ([What is this?](#what-is-this)).

## What is this?

**Right-click** a signal on either scope, or its waterfall, and a small card says what it is - from the band skimmer's list, the band plan and the over-the-beacon watch - with one or two buttons that do the likely thing. A left-click still tunes, as everywhere.

- **A calling window** (FT8, FT4, Q65, JS8): its name, how many signals are in it and the calls heard; **Decode FT8** (or FT4, Q65, JS8) tunes there in that mode, which brings the Digital workspace.
- **The lower or upper beacon**: **Decode CW**. **The middle beacon**: **Show its text** (Beacon › Middle beacon). **The multimedia beacon**: **Show the beacon** (Beacon › Bulletins). **A KG-STV picture**: **Show pictures** (Beacon › KG-STV), with the sender if heard. **AMSAT-DL's broadcast**: **Listen**.
- **SSB**: with its dial measured, **Listen** puts you on it exactly; otherwise **Listen and auto-tune**, as *Auto-tune onto the voice here* does.
- **CW**: **Decode CW**. **Data** nothing has identified: **Listen**, and **Try as** PSK31 or RTTY, marked as a guess. A signal the surveys found but NB does not decode: what is known about it, and **Listen**. A carrier, or a signal the skimmer has not looked at yet: **Listen**.
- **Over the beacon** or **LEILA?**: the event, and the callsign when your decoder heard exactly one station there.
- With nothing there, the card gives the band plan segment, and says so when the band skimmer is off (Settings › LNB & locks).

Under a line are the right-click's own items, as before: **Lock to this as the lower / middle / upper beacon** ([Telling it which signal is the beacon](#telling-it-which-signal-is-the-beacon)) and, in USB and LSB, **Auto-tune onto the voice here**.

Every button only tunes the receiver or shows a page; none transmits. While anything is on the air or an over is armed they are all greyed, with *Not while transmitting*.

## Over the beacon, and LEILA

QO-100's one hard rule is that no signal may be stronger than the beacon, and AMSAT-DL's ground station enforces it with **LEILA**: a siren put on top of a signal that breaks it, the cue to that station to turn down. OpenHamShack QO-100 NB watches the whole transponder for both, in the background, whatever you are tuned to. Nothing about it transmits.

- **Over the beacon** (amber): a signal with more power in a 1 kHz slice than the middle beacon has in its own, by 3 dB or more, for at least two seconds. A pile-up shows as one wide event: together, its callers put more power there than the beacon does.
- **LEILA?** (red): LEILA's siren - two steady tones about 205 Hz apart taking turns every 200 ms, for a few seconds, at about the beacon's power. That pattern was measured on real sirens in Brian's recordings of 17 October 2026, during the 7P8GE pile-up: replayed over 13 minutes of them, the detector found six sirens, all checked by hand, and nothing else. It is still labelled *LEILA?*: six sirens from one evening are few, and what makes LEILA mark one station and not another is not known (in those minutes many callers were over the beacon, and only six were marked). The siren comes in the FT8 slot **after** the offending over, where that station would be listening.

The **wide scope** marks each one with a tinted column through the spectrum and the waterfall and a caption (*+4 dB over beacon*, *LEILA?*): bright while it is happening, faded for a minute or two after. **Band** (**Ctrl + K**) lists the last 30 minutes at the top: time (UTC), frequency, what, and the callsign when your own decoder heard exactly one station there (during the event, or in the slot before a siren). **Click a row, or a caption on the scope, to tune the receiver there** in the mode you are in (USB and LSB put it at 1 kHz of audio, where you hear it). Nothing is judged until beacon lock has the beacon, and the line over the list says so.

**Keeping evidence.** *Settings › LNB & locks › Keep LEILA evidence (20 s of IQ)* (off by default) keeps the last 20 seconds of receive signal in memory - about 96 MB - and saves it to **Recordings** as a `…-LEILA` recording when a siren ends: the siren and the over before it. If you hear LEILA and nothing was marked, press **Save the last 20 s** over the list. Those recordings are what will confirm or correct the detector; send them as you would any recording ([Record a sample for the developers](#record-a-sample-for-the-developers)).

The watch costs about 4–5 % of one processor core. *Settings › LNB & locks › Watch for signals over the beacon and LEILA* turns it off.

## Second display

A separate window for another screen - a big waterfall across the room, or the mode panel at reading size. **Ctrl + D**, the screen button in the header, or **View › Second display** opens and closes it. In **Settings › Second display** choose which screen (automatically, any but the main window's), **full screen** on it, and what it shows: **Big waterfall + decodes**, with the frequency large across the top, or **Mode panel**. The panel there is a copy that shows everything and sends nothing. With one screen it is simply a second window. **Esc** leaves full screen on it (not while transmitting - then Esc unkeys, as everywhere).

![The second display's big waterfall.](screenshots/second-display-waterfall.png)

## Settings

**Settings** (Ctrl + , or the gear) has eleven pages. Nothing in Settings can key the transmitter. **Save** applies everything at once or, if anything is out of range, nothing, and says what; **Cancel** throws the changes away. A change to the radio, the sample rate, the sound devices or the simulator restarts the radio, which comes back receiving. The receiver gain applies at once, with no restart.

The ceiling, the timers and the radio itself can only be changed here, never from the main window, so a stray key can never raise a limit.

Besides the settings listed below:

- **Station** also holds the **licence** tick box, the same one as the Welcome's. Unticked, OpenHamShack QO-100 NB receives only on a radio; the simulator still transmits, into itself. Under the callsign, **Station's country** - by default the country your callsign puts you in (the prefix's, when you sign EA8/GM4BRI) - with its IARU region and the licence written for it, and a note when QO-100 is low or below the horizon from there.
- **Licence**: whose licence the station transmits under - *Follow the station's country*, a licence by name, or **My own licence** (a table of the segments your licence allows, with their power and whether the amateur-satellite service is allowed there) - your **licence class**, and the licence's own questions about the station. OpenHamShack QO-100 NB transmits to QO-100 only where that licence gives your class an amateur-satellite uplink on 2400.050-2400.300 MHz; where the licence or class is not known yet, it does not refuse to transmit - a standing warning on the transmit card says the check could not be made, until you choose one here.
- **Audio** also has **Noise reduction** and its strength ([Noise reduction](#noise-reduction)), and chooses the **Microphone**, **Speaker** and an optional **Second output** - receive audio for other software, such as a loopback device for WSJT-X or fldigi. Devices are remembered by name, so a USB headset is found on any port; one that is not plugged in is listed as *(not connected)*. **System default** says which device it means now, such as *System default (USB Audio CODEC)*: on Linux the name your sound settings use where PipeWire or PulseAudio will say it (otherwise their own word, *default* or *pulse*), on Windows the device Windows' sound settings call the default. *(none found)* means the system has no microphone, or no speaker, at all. Plugged something in, or changed the default, with Settings open? **Look again** lists the devices afresh, keeping what you had chosen. **Listen to the microphone** shows its level live (peaks should reach the amber, never the red) and **Play a test tone** plays 700 Hz for a second on the chosen speaker, both before you save.
- **Radio** also has the **S-meter**: its style, its units, the peak-hold needle, and the calibration offset for the radio in use, with **Calibrate…** ([The S-meter](#the-s-meter)).
- **Display** also chooses the **theme** (dark instrument, or light), the **text size** (100 %, 115 % or 130 %: see [Window sizes and text size](#window-sizes-and-text-size)), the **waterfall palette**, the waterfall **levels** (automatic, or a manual floor and contrast) and its **speed**. The **scope colours** are there too: presets **Classic** (the original look), **Amber**, **Green phosphor** and **High contrast**, or **Custom**, with a colour for the trace, the fill under it, the peak ghost, the peak markers, the grid and the background, the trace width (1-3 px), the fill on or off and its opacity, the grid's opacity, and **Reset to default**. A preview shows the choice before you save. They apply to every scope, the second display's too, in both themes (the scopes are dark in the light theme as well).
- **Second display**: open it, which screen, full screen, and what it shows (above).
- **Converters** holds the list of converters and its Add/Copy/Edit/Delete buttons ([Converters](#converters)); the table below lists only its three choices.

The table below is generated from the Settings window itself (`tools/settings-ref.py`), so its labels and sentences are exactly what the window shows.

<!-- settings-ref:begin (generated by tools/settings-ref.py; edit there, not here) -->

#### Station

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Callsign | text | (empty) | Used in macros, FT8 messages and the log. |
| Locator | text | (empty) | Maidenhead locator, e.g. IO86 or IO86ha. |
| Space bar / PTT button | Hold to talk / Toggle | Hold to talk | Hold: transmit while held. Toggle: press once to transmit, again to stop. Esc always stops. |
| Tune to usual frequency on mode | On / Off | On | Off: picking a mode only changes the mode - the dial stays exactly where it was. |
| FT8 and FT4 decoder | Automatic / WSJT-X's jt9 | Automatic | Automatic decodes with OpenHamShack's own decoder, a port of WSJT-X 2.7.0's, and falls back to WSJT-X's jt9 if it is missing or fails. WSJT-X's jt9 puts jt9 first. Whichever is not decoding checks the other's work, where both are installed. |
| Check for updates | On / Off | On | Look for a new version when the program starts and once a day while it runs. The check fetches one small signed file from the program's website and sends nothing about you or this computer. Off: only Help › Check for updates… looks. |
| Report stations heard to PSKReporter | On / Off | Off | Send the callsigns you decode in FT8, FT4, Q65 and JS8 to PSKReporter every five minutes: their call, frequency, mode, signal report and grid, with your callsign, locator and this program's name. |

#### Radio

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Radio | Simulator / Pluto family / SoapySDR (RX only) | Simulator | Which radio. The simulated transponder needs no hardware and is the default. *Restarts the radio when saved.* |
| Pluto address | text | `ip:192.168.2.1` | libiio URI: ip:192.168.2.1 (Pluto over USB), ip:pluto.local, ip:<address> (Pluto+, LibreSDR), usb:<bus>.<dev>.<n>. *Restarts the radio when saved.* |
| SoapySDR device | text | `driver=rtlsdr` | SoapySDR device arguments for a receive-only SDR, e.g. driver=airspy. *Restarts the radio when saved.* |
| Sample rate | 600 kS/s / 1.2 MS/s | 1.2 MS/s | Complex sample rate shared by receive and transmit. 1.2 MS/s keeps the transponder in the flat middle of the SDR's filter and lets one TX LO position reach almost the whole band; 600 kS/s costs about a third less CPU but cannot transmit on 2400.210-2400.290 MHz. *Restarts the radio when saved.* |
| Receiver gain control | Manual / Slow AGC / Fast AGC | Slow AGC | Receiver gain control in the SDR. |
| Receiver gain | 0 dB – 73 dB | 40 dB | Receiver gain when gain control is manual. |

#### Transmitter

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Transmitter | SDR (Pluto) / IC-9700 (CI-V) / Hamlib rigctld | SDR (Pluto) | What transmits. The SDR (the Pluto) is keyed by OpenHamShack QO-100 NB. An IC-9700 is keyed on the radio itself for voice: OpenHamShack QO-100 NB tunes it, follows it, shows and corrects where it lands, and keys it only for its own digital-mode overs if 'Key the IC-9700 for digital modes' is on. *Restarts the radio when saved.* |
| CI-V port | text | (empty) | The IC-9700's USB serial port: COM5 (Windows), /dev/ttyUSB0 or /dev/serial/by-id/... (Linux), or socket://host:port for a network serial port. *Restarts the radio when saved.* |
| CI-V baud rate | 4800 / 9600 / 19200 / 38400 / 57600 / 115200 | 115200 | CI-V speed. The IC-9700's CI-V USB Baud Rate is Auto by default, which follows this. *Restarts the radio when saved.* |
| CI-V address (hex) | 01 – DF | A2 | The radio's CI-V address. The IC-9700's default is A2. *Restarts the radio when saved.* |
| rigctld host | text | `127.0.0.1` | The computer rigctld runs on (127.0.0.1: this one). *Restarts the radio when saved.* |
| rigctld port | 1 – 65535 | 4532 | rigctld's TCP port (4532 unless started with -t). *Restarts the radio when saved.* |
| IC-9700 band (the IF) | 23 cm / 70 cm / 2 m | 23 cm | The IC-9700 band feeding the upconverter. |
| Receive dial follows the radio's knob | On / Off | On | Turning the radio's knob moves the receive dial too, as on a transceiver. Off: it moves only the transmit dial (split). |
| Switch the radio from FM to SSB | On / Off | On | When the radio is found in FM, which the narrowband transponder does not carry, switch it to SSB (USB on air), between overs. Off: NB never changes the radio's mode, and only warns. |
| Poll interval | 50 ms – 1000 ms | 100 ms | How often the radio is asked its frequency and whether it is transmitting: the delay before the TX marker follows its knob and before receive audio mutes. *Restarts the radio when saved.* |
| Largest TX lock correction | 20 Hz – 20000 Hz | 1000 Hz | The most TX lock may correct the external radio's uplink by. A larger error is shown, not corrected. A GPS-locked radio and upconverter need a few hundred hertz at most; a free-running IC-9700 is specified to about 650 Hz at 23 cm. |
| Receive audio while it transmits | Mute / Lower / Keep playing | Mute | Receive audio while the radio transmits. Mute stops your microphone hearing your own downlink from the speaker; the scopes, locks and level measurement carry on regardless. |
| Lower by | 3 dB – 60 dB | 20 dB | How far 'Lower' turns receive audio down while the radio transmits. |
| Key the IC-9700 for digital modes (CAT PTT) | On / Off | Off | Key the IC-9700 by CAT for NB's own digital-mode overs (FT8, FT4, Q65, JS8, PSK, RTTY and CW lines), as WSJT-X does, sending the audio to the radio's USB sound device and putting it in USB-D first. Never for voice: speech is always keyed on the radio. Off: NB never keys the radio. |
| Digital audio level | -40 dB – 0 dB | -10 dB | Level of the digital-mode audio sent to the IC-9700. Set it, with the radio's USB MOD Level, where the radio's power stops rising (its ALC reads with any audio): more makes splatter, not power. |
| Delay before audio (PA and relays) | 0 ms – 1000 ms | 100 ms | After NB keys the IC-9700, how long it waits before the audio starts, so the radio, its PA and the upconverter's relays have switched to transmit. A timed over (FT8) is keyed this much early. |
| Tail before unkeying | 0 ms – 1000 ms | 50 ms | After the last of the audio has played, how long NB waits before unkeying the IC-9700. |

#### LNB & locks

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| LNB is GPS-locked | On / Off | Off | The LNB has a GPS/reference-locked oscillator. Then the beacon error is mostly the SDR's own reference, and a first txCorr is predicted from it before ever keying. |
| Beacon lock | Auto / Hold / Manual | Auto | Beacon lock. Auto tracks a beacon and corrects the receive frequency continuously. Hold stops tracking and keeps the correction exactly as it is (a fading beacon, or your own overs). Manual: no tracking; set rxCorr by hand. In Hold and Manual nothing follows the LNB's drift. |
| Lock to | Middle (BPSK) / Lower (CW) | Middle (BPSK) | Beacon to lock to. The middle BPSK beacon is GPS-referenced and mid-band; the lower F1A beacon is the fallback (and is used automatically when the chosen one is not heard). |
| Beacon search range | ±2 kHz – ±55 kHz | ±50 kHz | How far either side of the expected position to search for a beacon. Unmodified LNBs need tens of kHz. |
| TX lock | On / Off | On | Find our own signal in the downlink while transmitting and correct txCorr. |
| Satellite round trip | 0.20 s – 0.40 s | 0.25 s | Satellite round trip (about 0.24-0.28 s depending on where you are). |
| Receive the multimedia beacon | On / Off | On | Receive AMSAT-DL's multimedia beacon (10489.995 MHz: bulletins, pictures, DX-cluster spots, transponder spectra) in the background, from the wide receive signal, whatever you are tuned to. About half a per cent of one core on a laptop. |
| Decode the middle beacon's text | On / Off | On | Decode the middle beacon's text (10489.750 MHz, 400 bit/s BPSK: DK0SB's K, L, M and N message blocks) in the background, whatever you are tuned to. Needs beacon lock, or a receive correction within a few hundred hertz. |
| Receive KG-STV pictures | On / Off | On | Receive KG-STV pictures (10489.6249 MHz USB: 320x240, about two minutes each, one 16x16 block at a time) in the background, whatever you are tuned to. Pictures of 50 blocks or more are saved. |
| Skim the whole band | On / Off | On | Find and name every signal on the transponder in the background, whatever you are tuned to: SSB voices with their dial measured, CW, data, the beacons and the FT8 windows (the Band view, and marks on the wide scope). |
| Band skimmer's share of the CPU | 1 % – 50 % | 10 % | The most of one processor core the band skimmer may use. Less only means SSB dials are measured more slowly; receiving is never held up. |
| Watch for signals over the beacon and LEILA | On / Off | On | Watch the whole transponder in the background for signals with more power than the middle beacon, and for AMSAT-DL's LEILA siren that marks them (the over-power list in the Band view, and marks on the wide scope). About 4 per cent of one core. |
| Keep LEILA evidence (20 s of IQ) | On / Off | Off | Keep the last 20 s of receive IQ (about 96 MB of memory) and save it to Recordings when a LEILA siren ends, or when you press Save in the Band view: evidence to check the siren detector against. Nothing is kept while this is off. |

#### Converters

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| LNB | a converter from the list | QO-100: LNB 9750 MHz | The LNB: the converter the receiver works through (9750 MHz for a standard 25 MHz-reference LNB). Beacon lock measures its error; you do not need to know it. *Restarts the radio when saved.* |
| Pluto's upconverter | a converter from the list | None: the Pluto transmits on 2400 MHz itself | The converter between the Pluto and 2400 MHz, if any. Usually none: the Pluto transmits on the uplink itself. *Restarts the radio when saved.* |
| IC-9700's upconverter | a converter from the list | None chosen (the IC-9700 cannot transmit until one is) | The IC-9700's upconverter to 2400 MHz, from the converter list. Required, and deliberately without a default: a guessed LO would put the uplink somewhere else entirely. An inverting (high-side) one turns the radio's USB into LSB and runs its knob the other way; OpenHamShack QO-100 NB converts. *Restarts the radio when saved.* |

#### Transmit & safety

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| TX gain ceiling | -89.75 dB – 0.00 dB | -10.00 dB | The most transmit gain any control can set. |
| Level guard | Warn only / Limit / Automatic | Limit | Own-signal level against the beacon: manual warns only; limit trims TX gain down when we are less than the margin below the beacon; auto also raises it back up (never above the ceiling). |
| Margin under the beacon | 0 dB – 30 dB | 6 dB | How far below beacon level our downlink should sit. |
| Transmit time-out | 0:10 min – 30:00 min | 5:00 min | Unkey after this long transmitting. |
| Dead-air unkey | 1 s – 30 s | 3 s | Voice modes: unkey after this long with no microphone audio. |
| UI watchdog | 0.5 s – 10.0 s | 2.0 s | Unkey if the user interface stops servicing the engine for this long. |
| TX audio low edge | 50 Hz – 1000 Hz | 300 Hz | - |
| TX audio high edge | 1500 Hz – 2950 Hz | 2700 Hz | Transmit audio high edge. The occupied width (high - low) may not exceed 2.7 kHz. |

#### Audio

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Noise reduction (NR2) | On / Off | Off | Noise reduction (WDSP's NR2) on what you hear in USB, LSB, CW and AM. Decoders always get the audio without it. |
| Noise reduction strength | 0 % – 100 % | 50 % | How far noise reduction may pull the noise down: 0 % leaves the audio untouched, 100 % up to 40 dB. |

#### Display

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Scope speed | 1 lines/s – 50 lines/s | 20 lines/s | - |
| Wide scope averaging | 1 – 16 | 2 | FFTs averaged per wide line. |
| Zoom scope averaging | 1 – 16 | 2 | - |

#### Simulator

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Other stations | On / Off | On | Populate the simulated band with other stations. *Restarts the radio when saved.* |
| Simulated LNB error | -60000 Hz – 60000 Hz | 1800 Hz | Simulated LNB error at start: how far high everything appears. *Restarts the radio when saved.* |
| Simulated drift | 0 Hz – 20000 Hz | 400 Hz | Size of the simulated LNB's slow wander. *Restarts the radio when saved.* |
| Drift timescale | 10 s – 7200 s | 600 s | Timescale of the simulated LNB's wander. *Restarts the radio when saved.* |
| Simulated TX error | -70000 Hz – 70000 Hz | -11000 Hz | Simulated SDR transmit error: where our signal really goes, relative to where we aim it. *Restarts the radio when saved.* |
| Gain where our signal equals the beacon | -89.8 dB – 0.0 dB | -20.0 dB | Transmit gain at which our simulated downlink equals the beacon. *Restarts the radio when saved.* |

<!-- settings-ref:end -->

## Keyboard shortcuts

**?** (or the **?** button in the header) shows them all over the window; any key closes it. The single-key shortcuts (arrows, letters, Space) do nothing while you are typing in a box; Esc still unkeys.

![The keyboard shortcuts overlay.](screenshots/shortcuts-1920.png)

| Keys | Does |
| --- | --- |
| **Tuning** | |
| ← / → | Tune down / up one step |
| Shift + ← / → | Ten steps |
| Ctrl + ← / → | 1 Hz |
| [ / ] | Smaller / larger step |
| Wheel | Step (over a digit of the readout: that digit) |
| F, or Enter on the readout | Type a frequency |
| Click | Tune to the click |
| Drag the passband | Tune by dragging |
| Ctrl + wheel | Zoom a scope |
| Z / Shift + Z | Zoom scope span in / out |
| **Transmit** | |
| Space | PTT (hold, or toggle - Settings › Station) |
| Esc | Unkey now, and cancel queued text or a CQ loop (with nothing on the air: close the Controls drawer) |
| Enter | Send the typed line (text modes) |
| F1 … F8 | Send macro 1 … 8 (CW and text modes) |
| F1 … F6 | Send voice memory 1 … 6 (USB, LSB, FreeDV) |
| **Modes and filter** | |
| Ctrl + E | Mode menu: every mode, recent first; type a name (Q65, JS8, HSmodem…) |
| Ctrl + 1 … 4 | USB, LSB, CW, AM |
| Ctrl + 5 … 8 | FT8, FT4, PSK31, RTTY |
| Ctrl + 9 / 0 | FreeDV, SSTV |
| , / . | Filter narrower / wider |
| R | RIT on / off |
| X | XIT on / off |
| S | Split on / off |
| N | Noise blanker |
| Shift + N | Noise reduction |
| M | Mute |
| A | Auto-tune onto the SSB station on the dial |
| Shift + A | Best audio for the station on the dial |
| **Beacon lock** | |
| H | Hold / back to Auto |
| Right-click on a scope | What is this?; lock to this as the lower / middle / upper beacon, or auto-tune there (USB, LSB) |
| Wheel over RX · beacon | rxCorr ±10 Hz (Shift: 1 Hz), in Manual |
| **Views** | |
| W | Next workspace: Digital, Voice, Watch (kept until you choose a mode) |
| Shift + W | Workspace follows the mode (Auto) |
| Alt + 1 … 9 | Recall memory 1 … 9 |
| Ctrl + J | Operate |
| Ctrl + L | Logbook |
| Ctrl + B | Memories |
| Ctrl + M | Multimedia beacon |
| Ctrl + K | Band skimmer |
| Ctrl + D | Second display |
| Ctrl + , | Settings |
| Ctrl + Shift + R | Record receive IQ / stop recording |
| Ctrl + Shift + P | Play an IQ recording / back to the radio |
| Ctrl + T | Light / dark theme |
| F11 | Full screen |
| ? | The shortcuts overlay |
| Ctrl + Q | Quit |

Q65, JS8, PSK63, PSK125 and HSmodem have no Ctrl + number: choose them with Ctrl + E, or on the rail. When you tab to a control, Space works that control instead of the TX button.

## Where things are kept

| | Linux | Windows |
| --- | --- | --- |
| Settings (`config.json`) and window preferences (`ui.json`) | `~/.config/openhamshack-nb/` | `%APPDATA%\openhamshack-nb\` |
| Log (`log.jsonl`), default ADIF export (`log.adi`), SSTV pictures (`sstv/`), what the multimedia beacon sent (`mmbeacon/`), the middle beacon's latest text blocks (`midbeacon/`), KG-STV pictures (`kgstv/`), files from HSmodem stations (`hsmodem/`) | `~/.local/share/openhamshack-nb/` | `%APPDATA%\openhamshack-nb\data\` |
| The program's own log (`openhamshack-nb.log`, see [Sending diagnostics](#sending-diagnostics)) | `~/.local/share/openhamshack-nb/logs/` | `%APPDATA%\openhamshack-nb\data\logs\` |
| IQ recordings (see [Record a sample for the developers](#record-a-sample-for-the-developers)) | `~/.local/share/openhamshack-nb/recordings/` | `%APPDATA%\openhamshack-nb\data\recordings\` |
| Voice memories (see [Voice memories](#voice-memories)) | `~/.local/share/openhamshack-nb/keyer/` | `%APPDATA%\openhamshack-nb\data\keyer\` |

These folders have been called `openhamshack-nb` since before the program was renamed OpenHamShack QO-100 NB: only the window's title and the Start menu entry changed on 17/10/2026, not where your settings, logbook and recordings live.

`OHS_NB_CONF` and `OHS_NB_DATA` move them. Your own memories are kept in `config.json`.

From a terminal, `openhamshack-nb --device sim` (or `pluto`, `soapy`) overrides the radio for one run without saving it, `--no-audio` runs with no sound card, and `openhamshack-nb --headless --seconds 10` runs the receiver alone without a window, printing a status line a second - useful for checking a radio from an SSH session. `openhamshack-nb --receive-only` opens the radio as usual but refuses every transmission for that run, whatever the window asks; start without it to transmit again. Headless never transmits. On Windows the same is `openhamshack-nb-console.exe`.

## Troubleshooting

**Find shows nothing, or "No Pluto found".** Type `ip:192.168.2.1` into **Pluto address** by hand and save: that reaches a Pluto plugged in by USB over its USB network adapter, and needs no USB permissions and no Avahi. If that fails too, check from a terminal: `ping 192.168.2.1` and `iio_info -u ip:192.168.2.1` (from `libiio-utils`). Without `avahi-daemon`, libiio 0.26's combined scan fails outright - the USB half too - so install it (`sudo apt install avahi-daemon`) for Find to cover everything; OpenHamShack QO-100 NB falls back to a USB-only scan and direct probes without it. For `usb:` addresses on Linux, `libiio-utils` must be installed, or the udev rule that opens up the Pluto's USB device silently does nothing. A Pluto+ or LibreSDR on Ethernet has its own address: look in your router's device list. On Windows, the PlutoSDR USB drivers must be installed before the Pluto is plugged in (the installer's **Install the PlutoSDR USB drivers** option), and `ping 192.168.2.1` from PowerShell is the check.

**"No Pluto at ip:192.168.2.1".** Nothing answered there within about five seconds; the program keeps running on no radio. Check the cable, the address, and (Windows) the drivers.

**"Pluto: could not set 1200000 S/s …".** The radio refused the sample rate by every route: `libad9361`'s routine, OpenHamShack QO-100 NB's own filter, and the 2.4 MS/s route without a filter. The sentence lists why each failed. Install `libad9361-0` if it says it is not installed, check the firmware, and try 600 kS/s. A notice saying the firmware *will not load the AD9361's FIR … so the radio runs at 2.4 MS/s* is not an error: it has already worked round it.

**"The installed libiio is not the 0.2x series", or "libiio could not be loaded" (Windows).** The copy of libiio 0.26 inside OpenHamShack QO-100 NB is missing or damaged: reinstall OpenHamShack QO-100 NB. (A libiio 1.0 installed elsewhere on the PC does not matter.)

**No sound.** Settings › Audio: is the right **Speaker** chosen, and does **Play a test tone** play? If no devices are listed at all, PortAudio is missing (Linux: `python3-pyaudio`). Then check **Volume** and **Mute** (M) on the rail, and that AGC is not **Off** with the gain at its lowest. Another program holding a bare ALSA device can keep it from being opened; choose the system default, or the PulseAudio/PipeWire device.

**The microphone does nothing, or transmit stops after three seconds.** That is dead air: the program heard nothing from the microphone. Settings › Audio, **Listen to the microphone**, and speak: the meter should move. Choose the right **Microphone**, and raise **Mic gain** in the Microphone card.

**FT8 or FT4 is greyed, with "ohsdigi, OpenHamShack's FT8, FT4 and Q65 decoder, did not load".** The program's own decoder is missing or damaged: reinstall OpenHamShack QO-100 NB. With the `all` package, which has no ohsdigi, install WSJT-X instead: `sudo apt install wsjtx`.

**FT8 shows no decodes.** Check the dial (10489.540 is the usual place), that the signals sit inside the zoom scope's audio window, and that the computer's clock is right to within a second - FT8 depends on it (on Linux, `timedatectl` should say *System clock synchronized: yes*).

**FreeDV is greyed: "Install codec2 for FreeDV".** `sudo apt install libcodec2-1.2` (or `libcodec2-1.0` on Debian 12).

**The TX button is greyed.** Hover over it: it says why. The usual reasons are the licence tick box, a receive-only radio, AM, and a frequency where your mode may not transmit (move into the right segment).

**RX · beacon never locks.** The dish is not on the satellite, the LNB's error is beyond the search range (widen it to ±55 kHz), or the **LNB** chosen in Settings › Converters is wrong for yours (9750 MHz for the usual one). If you can see the beacon on the scope, right-click it and choose **Lock to this as the … beacon**.

**RX · beacon locked to the wrong signal.** Right-click the real beacon and **Lock to this as the … beacon**; beacon lock stays there. Click the badge: **Last refused** shows what else it was offered and why it said no - worth sending with a report. Before 0.1.4 a loud SSB station beside the middle beacon could take the lock, more often with the search widened to ±55 kHz.

**Overruns climb in the status strip.** The computer is not keeping up with the receiver. Use 600 kS/s, reduce **Scope speed** in Settings › Display, close other programs. On a Raspberry Pi, use the 600 kS/s rate.

**It will not start at all.** On Linux, run `openhamshack-nb` from a terminal and read what it says; on Windows, use **OpenHamShack QO-100 NB (console)** from the Start menu. "The window needs PyQt6" means `python3-pyqt6` is missing. Either way, the end of the program's own log (below) usually says why.

## Sending diagnostics

When something goes wrong, or looks odd on the air, **Help › Save diagnostics…** makes one zip file to email to Brian. It holds:

- the program's log of this run and the ones before it;
- your settings (`config.json` and `ui.json`) - your callsign and locator are left in, anything that looks like a password is removed;
- `report.txt`: the program and system versions, which libiio, WSJT-X, FT8/FT4 encoder, codec2 and sound devices it found, the radio's firmware, model and serial, the state of the locks and corrections, and your screen's size and scaling;
- a picture of the main window (only the window, not the rest of your screen);
- the last two minutes of status, a line a second.

The dialog lists every file before anything is saved. **Save…** asks where (the Desktop on Windows, your home folder on Linux); **Open folder** then shows the zip, ready to attach. Nothing is sent by the program itself.

The log is always on: `openhamshack-nb.log` in `~/.local/share/openhamshack-nb/logs/` on Linux and `%APPDATA%\openhamshack-nb\data\logs\` on Windows (**Help › Open log folder** goes there). It keeps about 10 MB - five old files beside the current one - and records start-up, the radio opening and closing, beacon and TX lock coming and going, the IC-9700's link, overruns, which settings changed (not what you set them to) and any error. For more detail, start it with `-v`: `openhamshack-nb -v` on Linux, or `openhamshack-nb-console.exe -v` on Windows, which also shows the log live in its console window.

## Record a sample for the developers

When you hear or see something odd - a signal that will not decode, beacon lock refusing the beacon, a spur, interference - a recording lets Brian look at exactly what your radio received, at his desk, as often as he likes. It records the radio's whole receive signal (everything the wide scope shows, not just the audio), with a note of how your station was set up.

1. Tune to where the odd thing is, in the mode you were using.
2. **File › Record receive IQ…** (Ctrl + Shift + R). The window says how much disk it takes before anything is written - at 1.2 MS/s about **4.8 MB a second, 290 MB a minute** - and how much room there is. A minute or two is usually plenty; set **Stop by itself after** if you would rather not watch the clock (it is remembered).
3. **Record**. While it records, the status strip at the bottom shows a red **● REC** with the time and size so far. Carry on operating as normal - tuning, changing mode, even transmitting all go on; what you transmit is never recorded.
4. **File › Stop recording** (Ctrl + Shift + R again) stops it. A message says the recording is saved, with its name.

**File › Open recordings folder** opens the folder: `%APPDATA%\openhamshack-nb\data\recordings\` on Windows, `~/.local/share/openhamshack-nb/recordings/` on Linux. Each recording is **two files with the same name**, for example `openhamshack-nb-20261007-182100Z-10489.540MHz-FT8.sigmf-data` and `….sigmf-meta`. **Send both**: the `.sigmf-data` file is the signal, the `.sigmf-meta` file says what it is (frequency, sample rate, when, your LNB and its correction, beacon lock, gain, radio and firmware, the program and Windows version, your callsign) - one without the other is no use. The data file is too large for email; a file-sharing link (OneDrive, Google Drive, WeTransfer) is the way to send it. A note of what you noticed, and roughly when in the recording, helps.

Recording takes almost no processing, so it does not disturb receive. If the disk cannot keep up (a slow USB stick, a nearly full disk), the program drops pieces rather than holding up the radio; the message at the end says so, and the files record where the gaps are. Stopping the radio, a Settings change that restarts it, or closing the program also ends a recording, and saves it properly.

The files are in SigMF, an open format: any SigMF tool (inspectrum, GNU Radio, the `sigmf` Python package) can open them too.

## Play a recording

**File › Play IQ recording…** (Ctrl + Shift + P) plays a recording - yours, or one somebody sent you - through the receiver in place of the radio: the scopes, beacon lock, the decoders and the speaker all work on it exactly as on the air, so an FT8 period recorded last week decodes again, at the time it was sent. Choose either file of the pair; both must be in the same folder.

While it plays, the status strip shows **▶ PLAYBACK** with the recording's name, how far in it is, and when that moment was recorded. Nothing can be transmitted (the TX button says why) and nothing new can be recorded. You can tune anywhere the recording covers; tuning outside it is refused. **File › Loop playback** starts it again from the beginning when it ends; without it, the end is silence and a message.

**File › Back to the radio** (Ctrl + Shift + P again) returns to your radio. The recording's own frequency, mode and LNB correction are used while it plays and are never saved: your own come back as they were.

## Analyse a recording

A recording (above) is a few hundred megabytes, too much to look at by eye,
and Brian is not always free to look at it for you. **`--analyse`** reads one
and writes a short report instead - no radio, no window, nothing opened. A
terminal is needed for this one (Linux: a normal terminal; Windows: open
`cmd.exe` or PowerShell in the install folder, or run `openhamshack-nb-console.exe`
once to see where it is installed).

```
openhamshack-nb --analyse openhamshack-nb-20261007-182100Z-10489.540MHz-FT8.sigmf-data
```

(either the `.sigmf-data` or `.sigmf-meta` file name works - both must be
in the same folder, as they always are). It takes a minute or two for a
quarter of an hour of recording, and writes, beside the recording (or wherever `--out
a-folder` says):

- **`report.txt`** - a page of plain numbers: the radio and settings it was
  made with, the noise floor and how far the transponder rises over it,
  the middle beacon's strength and the LNB's measured offset and drift,
  whether the lower and upper beacons were heard, any clipping or gaps in
  the recording, FT8 decodes in the calling segment (counted twice over -
  ohsdigi, OpenHamShack's own decoder, and WSJT-X's jt9 where WSJT-X is
  installed, so the two can be checked against each other), and any SSB voice signals found,
  with where auto-tune puts their carrier;
- **`report.json`** - the same numbers, for a program rather than a person;
- a few pictures (`wide.png`, `beacon.png`, `ft8.png`) of the spectrum, the
  beacon's frequency and strength over time, and FT8 decodes per time
  slot - skipped, with a note in both reports, on a machine with no
  `matplotlib` installed.

**`--minutes 2`** looks at only the first two minutes - useful for a quick
check of a long recording. A recording of something other than QO-100 (the
wrong frequency, or made by other software) still gets the noise floor and
clipping check; the beacon, FT8 and SSB sections say plainly that they were
skipped, and why, rather than reporting nonsense about a transponder that
is not there.

**`--extended`** adds the slow sections a developer asks for on a long
recording - the multimedia beacon, signals stronger than the beacon (with
a check for the LEILA warning), SSB auto-tune every ten minutes, FT4, Q65,
JS8 and PSK31 counts, and a band census - each also available on its own
(`--mmb`, `--overpower`, `--ssb-scale`, `--other-modes`, `--census`).
These are slow - a 16-minute recording of a busy evening took 16 minutes
in one process - so the analysis uses several processor cores at once
(8 minutes with eight, on a computer that was busy with other work):
**`--jobs N`** sets how many worker
processes (the default is one per core less one, fewer if the computer is
short of memory - about five on an 8 GB laptop). **`--jobs 1`** does
everything in one process, as before; the report is the same either way.
While it works, a line goes to the terminal as each part starts and
finishes, so a long run can be seen to be moving (**`--quiet`** turns them
off).

## Not yet verified

OpenHamShack QO-100 NB has been built and tested against its own simulator. Be clear about what that does and does not show.

- **Auto-tune and best audio** were tried on air on 7 October 2026, receive only, with a weak dish (the middle beacon 8-10 dB over the noise). Auto-tune answered on about a third of its tries at real voices, and refused the rest. Its answers agreed with each other from four different starting dials to within a few hertz. On a recording, each matched the station's own faint leaked carrier to within 4-7 Hz. It refused the middle beacon and the data signals every time. Best audio's choices took the noise between words down by 8-15 dB on those stations, but nobody has listened to judge them by ear yet. Both have been heard on QO-100 only, not on HF.
- **Receive has been on air; transmit has not.** On 5 October 2026 it received the real QO-100 downlink with an ADALM-Pluto on Windows 11 at 1.2 MS/s: beacon lock locked on the middle beacon, an LNB 27 kHz out found inside the default search range, no overruns. A Pluto nano and a LibreSDR have received with it on Linux. Nothing has been transmitted on air with it, and it has not run against a Pluto+, a SoapySDR receiver, or a Raspberry Pi. The Pi's figures are estimates from the design's processing budget, not measurements.
- On the Pluto, the parts most likely to need work are the filter it loads when `libad9361` is not installed, attribute names that differ between firmware versions, and what the radio does if the transmit stream runs short.
- **The IC-9700 as transmitter** has run only against an emulated radio written from Icom's documents; the list of what a real one must confirm is at the end of *Transmitting with an IC-9700*.
- **The control pad** has never been used with a real AKP03E in this program: everything is tested against a simulated pad built from reports captured on a real one under Linux. On Windows and macOS which part of the pad is opened, and how its pictures are sent, follow other open-source drivers and hidapi's own code; the first real pad on Windows is the test. If it does nothing, **Settings › Control pad › Copy controller report** says what was seen.
- **TX lock is proven only against the simulator**, and beacon lock on air only on the middle beacon. The upper beacon's tone direction and the 0.25 s round trip are assumptions until checked on air.
- **The S-meter's calibration** is tested against the simulator only. Whether a Pluto's gain steps really move dBFS one-for-one (which is what lets a calibration survive a gain change) is unmeasured; calibrate at the gain you use until it has been checked.
- **Noise reduction** has been measured on the simulator's synthetic speech in synthetic noise, not heard on a real signal. Whether 50 % is the right default, and how it sounds on real SSB and CW, is for the ear to judge on air; its cost on a Raspberry Pi is an estimate.
- **FT8 and FT4 sending** uses OpenHamShack QO-100 NB's own encoder. It gives the same symbols as WSJT-X 2.7.0's for every message it was compared on (over 150,000, every message type), and WSJT-X's `jt9` decodes what it sends, on Linux and on Windows; but nothing has been sent on air with it yet. The Raspberry Pi (`arm64`) package's encoder has been built but never run on a Pi.
- **HSmodem station to station** has worked only between OpenHamShack QO-100 NB engines on the simulator and against HSmodem's own modem code compiled from source - all ten speeds, both ways. Not yet tried: a real HSmodem station on the air, and DJ0ABR's Windows program itself (the test machine has no sound card for it to play into). Whether HSmodem's program reads OpenHamShack QO-100 NB's ZIP files as Windows' own ZIP library does (which was checked) is assumed.
- **The middle beacon's text** has been decoded from Brian's recordings of the real beacon made on 7 October 2026 - the 5-minute one played through OpenHamShack QO-100 NB itself, with beacon lock, decoded all 12 blocks; the decoder on its own decoded 29 of the 30 blocks in a 13-minute one with the beacon 8-10 dB over the noise, and 430 of 433 in a 3-hour one (the same four texts throughout) - but not yet live from a radio. Its FEC frames are not decoded.
- **KG-STV pictures** have been received only from Brian's 3-hour recording of 7 October 2026, played back through OpenHamShack QO-100 NB (beacon lock and all): four pictures from VU2SAA, DL4CQ and DG8RP, 1194 of their 1200 blocks - not yet live from a radio. KG-STV's four-level FSK has never been heard, so pictures sent that way are untested; the picture colours rest on JPEG's standard conversion, which KG-STV's own program may round a level or two differently.
- **Sending KG-STV pictures** (from 0.1.18) is proven against NB's own receiver - which was itself proven on real stations' pictures - on the simulated transponder and an emulated IC-9700, not yet against KG-STV's own program or on the air.
- **The band skimmer** has run over Brian's recordings of 7 October 2026 (the 3-hour one and four shorter ones, faster than real time, with beacon lock's corrections from the same recordings), not yet live from a radio. It listed all but 2 of the 69 stations in the labelled set taken from the 3-hour one. Its dials are auto-tune's answers, with auto-tune's accuracy on those weak voices: of the answers it gave while a labelled station was on air, about half were within 10 Hz of the station's own leaked carrier (12 of 23) and the rest a pitch or so off - which is why a dial is shown as measured only once two listens agree. On those recordings that happened rarely: auto-tune answers about one 4-second listen in seven on such weak voices, and most stations were never answered twice. On a stronger dish it should answer far more often.
- **Over the beacon and LEILA** have been run only over Brian's recordings of 17 October 2026 (receive, on his Mac, during the 7P8GE pile-up), not yet live from a radio; the six LEILA sirens in them are the only ones the detector has met.
- **The multimedia beacon** has been received only from the simulator. Its decoder gives the same frames as DJ0ABR's own HSmodem receiver on HSmodem's own signals, but the real beacon's filtering, exact frequency and content (pictures, the CW skimmer's format) are unpublished or unconfirmed.
- On Windows, the installer's PlutoSDR USB drivers option has been tried only on a Windows 11 virtual machine without a desktop session, so Windows' *install this device software?* question has not been seen through it; the built-in libiio 0.26 has been checked there with no other libiio on the machine.
- **Updating itself** has been tested against a signed test feed on this computer only. The first real update will be from the first release that carries it to the one after; the Windows installer's unattended run and restart have not yet been tried on Windows.

When you do try it on air: **receive first**, then transmit into a dummy load, then low power on the satellite, watching **Own signal vs beacon**.

## Known problems

None listed for this release. What has not been checked on real hardware is under [Not yet verified](#not-yet-verified) - read that before transmitting.
