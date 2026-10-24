# OpenHamShack Radio user guide

OpenHamShack Radio is a transceiver for the amateur bands, 160 m to 6 cm. It runs on your own Linux or Windows computer and works a software-defined radio directly - an ADALM-Pluto, Pluto+, LibreSDR or Pluto nano on VHF and up, a Hermes-Lite 2 on HF, or a receive-only SDR - doing the receiving, the demodulating and the transmitting itself. It is one window, used at the machine it runs on; there is no browser console and nothing to log in to. It is the terrestrial sibling of OpenHamShack QO-100 NB (the QO-100 transceiver) and shares its engine.

It starts on a built-in **simulator** - simulated bands with SSB, CW and FT8 stations, IBP beacons and UK FM repeaters that open to the right tone - so you can learn every control with no radio, and nothing can reach the air by accident.

It holds every transmission inside what your licence class allows - the licence of the country your callsign (or your choice) puts the station in - warns when its power estimate is over that class's limit (and unkeys when a radio that measures its own output goes over it), and warns when you leave what that country's band plan (or its IARU region's) intends. That is a help, not a substitute: the licence condition is yours to keep.

**This is a preview, tested on the simulator only.** Nothing has been tried on a real radio or on air. Pluto receive and transmit on 2 m and 70 cm are unproven; the Hermes-Lite 2 has only met a software emulator of itself; every power figure is an estimate from numbers you type in. Read [Not yet verified](#not-yet-verified), at the end, before you connect anything to an antenna.

## What it is, and what it is not

It is:

- A receiver for whatever part of a band your radio's sample rate shows, with a bandscope and waterfall across it, a zoomed scope around your frequency, and the band plan drawn along the top.
- A half-duplex transmitter for the Pluto family and the Hermes-Lite 2: receive audio is muted while you transmit.
- **A licence guard**: your class decides where you may transmit, sub-allocation by sub-allocation, from the licence tables of the country the station is in (the UK's are Ofcom's: Foundation, Intermediate, Full). For a country whose licence is not written into OpenHamShack, you enter your own licence's segments and power limits. Outside them the TX button stays locked and says why. This is always on. Power is **advisory until measured**: an estimated power over the class's limit warns; a measured one unkeys.
- **A band-plan guard**: the band plan's segments - the RSGB 2026 plan in the UK, the IARU plan of your region elsewhere - drawn on the scope and checked on every key-up. By default it warns and lets you transmit; it can refuse instead. Beacon and satellite sub-bands are refused whatever it is set to.
- **A power chain** per band: your radio's output, your amplifier's gain, feeder loss and antenna gain, so the program can estimate your power at the antenna in your licence's terms and warn when the estimate is over.
- Modes: USB, LSB, CW (keyer and decoder), AM (receive and transmit), FM with CTCSS, repeater shift, reverse and the 1750 Hz toneburst, FT8 and FT4, PSK31/63/125, RTTY 45.45 baud / 170 Hz, FreeDV and SSTV.
- A band bar with three band-stack registers per band, VFO A and B, split, RIT and XIT.
- A PTT sequencer that keys a PA's PTT line (a USB-serial adapter's RTS or DTR) before RF and releases it after.
- A logbook with ADIF export, and memories seeded from the band plan.

It is not:

- Tested on hardware. See the preview note above, and [Not yet verified](#not-yet-verified).
- A rig controller. It does not drive a transceiver over CAT; it *is* the transceiver, with an SDR as its radio.
- A 6 m station on its own. Neither radio reaches 6 m (see [Choosing a radio](#choosing-a-radio)); the band works only through a 6 m transverter ([Converters](#converters)).
- A transverter controller in the full sense. Bands work through transverters ([Converters](#converters)), but a transverter's own PTT line, relay or sequence is not switched per band yet: the PTT sequencer has one line for everything.
- A satellite station. QO-100 is OpenHamShack QO-100 NB's; LEO satellites with Doppler are not here, and the satellite sub-bands are refused.
- A recorder. There is no audio or IQ recording.

## What you need

- A Linux computer: Debian 12 or 13, Ubuntu 24.04 or later, or Mint built on those; or a Windows 10 or 11 PC, 64-bit (see [Installing on Windows](#installing-on-windows) for what differs there). A screen at least 1024 × 600 (see [Window sizes and text size](#window-sizes-and-text-size)). (A Raspberry Pi 400/500 is a target, but OpenHamShack Radio has not been run on one.)
- To transmit and receive on VHF and up: an **ADALM-Pluto, Pluto+, LibreSDR or Pluto nano**, a dummy load, and the use of a spectrum analyser. The Pluto's own output is a few milliwatts and has **no output filter**: its output is checked into a dummy load on the analyser before it drives any PA (see [Before you key a Pluto into anything](#before-you-key-a-pluto-into-anything)), and it is never connected straight to an antenna.
- To transmit and receive on HF: a **Hermes-Lite 2** on your network, with its N2ADR filter board.
- To receive only: an RTL-SDR, Airspy, SDRplay or HackRF through SoapySDR.
- A sound card (the computer's own is fine) and a microphone for voice. With no sound card the program runs silent.
- For FT8 and FT4 on Linux: nothing more with the `amd64` and `arm64` packages, which carry their own encoder and decoder; with the `all` package, WSJT-X (its `jt9` decodes and its `ft8code`/`ft4code` encode). Installed beside the others, WSJT-X's `jt9` is the fallback decoder and checks every slot's decodes. The Windows installer carries what it needs.
- For transmitting: an amateur licence. OpenHamShack Radio has the UK's (Ofcom) licence and RSGB band plan written in, and the IARU Region 1, 2 and 3 band plans; for any other country you choose a licence or enter your own (Settings › Licence & plan).

## Installing on Linux

Download the package for your computer from the website and check it against the SHA-256 printed beside it: `openhamshack-radio_<version>_amd64.deb` for a PC or laptop, `openhamshack-radio_<version>_arm64.deb` for a Raspberry Pi 4, 400, 5 or 500 running 64-bit Raspberry Pi OS, and `openhamshack-radio_<version>_all.deb` for anything else. `dpkg --print-architecture` says which you have. The first two carry OpenHamShack Radio's own FT8/FT4 encoder and decoder; the `all` one makes and decodes FT8 and FT4 signals with WSJT-X's `ft8code`, `ft4code` and `jt9` instead, and is otherwise the same.

```
sha256sum openhamshack-radio_*.deb
sudo apt install ./openhamshack-radio_<version>_amd64.deb
```

Use `apt install ./…` rather than `dpkg -i`: apt fetches what the package needs from your normal repositories in the same step. It needs `python3-numpy`, `python3-pyqt6` and `python3-pyaudio`, and by default also installs these **recommended** packages, each of which adds one feature:

| Package | What it adds |
| --- | --- |
| `python3-libiio` | The Pluto family (ADALM-Pluto, Pluto+, LibreSDR, Pluto nano) |
| `libiio-utils` | `iio_info`, and the Pluto's USB permission rule, which does nothing without it |
| `libad9361-0` | The Pluto's own routine for low sample rates; without it OpenHamShack Radio loads its own filter |
| `avahi-daemon` | Lets **Find** in Settings see a Pluto by name on the network, and stops libiio's scan failing outright |
| `wsjtx` | FT8 and FT4 with the `all` package (its `jt9` decodes, its `ft8code`/`ft4code` encode); with the others, the fallback decoder and the check on every slot |
| `libcodec2-1.2` or `libcodec2-1.0` | FreeDV (apt picks whichever your release has) |
| `python3-soapysdr` | Receive-only SDRs through SoapySDR |

The Hermes-Lite 2 needs no package: it is reached over UDP with Python's own sockets. For a receive-only SDR, add its SoapySDR module: `soapysdr-module-rtlsdr` or `soapysdr-module-airspy`.

A package you leave out never stops the program: the feature that needs it says which package to install, and everything else works.

OpenHamShack Radio installs beside OpenHamShack QO-100 NB without touching it: separate program, separate settings, separate log. The two cannot use the same radio at the same moment.

Start **OpenHamShack Radio** from the applications menu, or `openhamshack-radio` in a terminal.

**Or the AppImage**, one file for any 64-bit PC running Linux from Debian 12 or Ubuntu 22.04 on, with no installing: download `OpenHamShack-Radio-<version>-linux-x86_64.AppImage`, check its SHA-256, make it executable (`chmod +x`) and run it. It carries its own Python, Qt and libraries; a Pluto needs the system's libiio (`sudo apt install libiio0` or your distribution's equivalent), and WSJT-X's `jt9` for FT8 and FT4 decoding if you have it installed.

## Installing on Windows

Download `openhamshack-radio-<version>-setup.exe` and double-click it. It installs for you alone into `%LOCALAPPDATA%\Programs\OpenHamShack Radio` (the Pluto's USB drivers, below, are the one part that asks for administrator permission), and adds **OpenHamShack Radio** and **OpenHamShack Radio (console)** to the Start menu. The console one is the same program with a text window behind it, for reading an error at start-up. If OpenHamShack Radio is running, close it before installing a newer version over it.

It installs beside OpenHamShack QO-100 NB without touching it: separate folder, Start menu entries, uninstaller, settings and log. The two cannot use the same radio at the same moment.

**The installer is code-signed by 360 Technology** (from the release after 0.1.5; earlier ones are unsigned). Windows may still be cautious about a new publisher for a while:

- **SmartScreen** can say *Windows protected your PC* until the publisher has built up a reputation with Microsoft, which takes downloads and time. Check it names **360 Technology**, then choose **More info** and **Run anyway**.
- **Smart App Control** (Windows 11: Settings → Privacy & security → Windows Security → App & browser control → Smart App Control) blocked the unsigned installers outright. Signed ones should get further, but it also checks the third-party libraries inside, not all of which are signed by their makers, and it has not yet been tried with it On. If it blocks OpenHamShack Radio, it must be **Off** - and Windows will only turn it back on by resetting the PC, so decide on a test machine rather than someone's everyday one.
- A PC in **S mode** cannot run it at all.

The simulator, all the signal processing, the licence and band-plan guards, sound, FreeDV and FT8 are built in, and so is what a Pluto needs.

**For a Pluto, there is nothing to download.** libiio 0.26 is built in (a machine that also has ADI's libiio 1.0 is fine: OpenHamShack Radio uses its own copy). The USB drivers come with the installer: leave **Install the PlutoSDR USB drivers** ticked, and install **before plugging the Pluto in**. They give the Pluto its USB network adapter, so it appears at `ip:192.168.2.1` exactly as on Linux. Two questions follow, both from Windows: administrator permission for the drivers (the only part that needs it), then *Would you like to install this device software?* from Analog Devices International UC - answer **Install**. If either is refused, OpenHamShack Radio is still installed and the installer says the drivers are not; run it again with the option ticked. When the drivers are already there - from OpenHamShack QO-100 NB's installer, for one - the option is not shown at all. They appear in Settings → Apps as *PlutoSDR-M2k-USB-Win-Drivers* and stay if OpenHamShack Radio is uninstalled. With the Pluto plugged in, `ping 192.168.2.1` from PowerShell should answer; then **Find** in Settings › Radio lists it.

**FT8 and FT4 need no WSJT-X install**, and both send and receive: the installer carries OpenHamShack Radio's own FT8/FT4 encoder and decoder. (Up to 0.1.21 it also carried WSJT-X 2.7.0's decoder as the fallback; a WSJT-X you install yourself still takes that part.) The Country column's `cty.dat` comes with every package too, the `.deb` included.

What is not built in:

1. **For a Hermes-Lite 2**, nothing to install, but Windows Firewall asks the first time the program looks for one: allow OpenHamShack Radio on **private networks**, or the radio's replies never arrive. (Not yet tried with a real radio on Windows.)
2. **Receive-only SDRs through SoapySDR, and the PTT sequencer's serial line, are Linux-only** for now. On Windows leave **PTT line** at **None**; set to Serial, transmit is refused with a sentence saying the port could not be opened.

Uninstalling (Settings → Apps, or the uninstaller in the Start menu) leaves your settings and log in `%APPDATA%\openhamshack-radio\`.

## Updates

From the release after 0.1.8, OpenHamShack Radio keeps itself up to date. A few seconds after it starts, and once a day while it runs, it fetches one small signed file from its website saying what the newest version is. Nothing about you or your computer is sent - only "openhamshack-radio/<version>", as any download would.

When there is something newer, a strip appears above the scopes: **OpenHamShack Radio 0.1.9 is available**, with **Install and restart**, **Later** and **What's new**.

- **Install and restart** downloads the new version, checks that it is exactly the file 360 Technology signed, and installs it. On Linux your system asks for your password (apt installs the package, as when you first installed it); then **Restart now**. On Windows the program closes, the installer runs by itself, and OpenHamShack Radio starts again.
- **It never installs or restarts while you are transmitting or recording.** The button waits, and says why; an over is never cut short.
- **Later** hides the strip until the next start. **What's new** opens the release notes on the website.
- **Help › Check for updates…** checks there and then, and says what the last check found - including why, when the site could not be reached or what it offered could not be proved genuine. Nothing that cannot be proved is ever installed, and a failed check never interrupts you.
- **Settings › Station › Check for updates** turns the automatic check off.

On Linux without a password prompt (no `pkexec`), the strip gives the command to type instead: `sudo apt-get install -y …`. A copy run from source never updates itself.

## The first time it starts

A short **Welcome** opens over the window: three steps, with **Back**, **Skip** and **Next** at the bottom.

1. **Your station.** Your callsign and locator (IO86 or IO86ha). Both are used in macros, FT8 and JS8 messages and the log (JS8 will not send without a callsign); both can be left empty and filled in later in Settings › Station. A locator that is not a Maidenhead locator is refused with a sentence saying so.
2. **Before you transmit.** **Your licence class**: the classes of the licence written for the country your callsign puts you in - in the UK, Foundation, Intermediate or Full. **None is chosen for you.** Where no licence is written into OpenHamShack for your country yet, there is no class to pick and it says so: OpenHamShack Radio will receive, and to transmit you choose a licence or enter your own in Settings › Licence & plan. Until you pick one, OpenHamShack Radio receives normally but refuses every transmission, and the licence chip, the TX button and the status strip say *No licence class chosen*. (Foundation used to be preselected; a default that is wrong for most people is worse than one choice made once.) Below it, the rules the program keeps - it holds every transmission inside what your class allows and warns when the power chain you enter estimates more than your class's limit; it warns when you leave what your country's (or IARU region's) **band plan** intends and never transmits on the beacon or satellite sub-bands; a Pluto has **no output filter**, so its output is checked into a dummy load on a spectrum analyser before it drives any PA and it is never connected straight to an antenna; Space or the TX button keys and **Esc always stops** - and a tick box: *I understand, and I hold an amateur licence of the class I have chosen above.* **Leave it unticked to listen only** - with or without a class. Transmitting needs **both** a class and the box ticked. Ticking it with no class chosen is not accepted: the box vouches for *the class I have chosen above*, so **Start listening** comes back to this page and asks you to choose one, or to leave the box unticked to listen only. Until it is ticked - here, or in Settings › Station - the TX button, the Tune button, the toneburst and every send button stay locked, and pressing them says why. If your class cannot be saved when you press **Start listening**, the Welcome comes back to this page and says why under the class.
3. **Your radio.** **Simulator** (the default), **ADALM-Pluto family** with its address (`ip:192.168.2.1` unless yours is elsewhere), or **Hermes-Lite 2** (found on your network by itself). A receive-only SoapySDR radio is chosen in Settings › Radio. **Start listening** finishes.

![The Welcome's licence step: your class, the rules, and the tick box that unlocks transmit.](screenshots/welcome-licence.png)

**Skip**, on every step, closes the Welcome there and then. It marks the Welcome as seen and saves nothing else - not what you typed, not the class, not the radio, not the tick box - so you carry on with the radio already chosen (on a new install, the simulator), and the licence stays unacknowledged. In OpenHamShack Radio that locks transmit on the simulator too: nothing transmits until you choose a class and tick the box in Settings.

The Welcome shows once. **Help › Welcome…** opens it again; the class can also be changed in Settings › Licence & plan.

Where the station is decides whose rules apply. **Settings › Station** shows the country your callsign puts you in - the prefix's country when you sign EA8/GM4BRI - with its IARU region and the licence written for it; **Station's country** overrides it. **Settings › Licence & plan** then has:

- **Licence**: *Follow the station's country* (the default), a licence by name, or **My own licence**, which opens a table: one row per segment your licence allows, its most power, how that power is measured (PEP, mean, carrier, ERP or EIRP - ERP and EIRP are worked out from the antenna gain on Bands & power), and whether the amateur-satellite service is allowed there. Outside every row, transmit is refused. Use it in a country whose licence is not written into OpenHamShack; until you do, transmit stays locked there and the TX button says why.
- **Licence class**: the classes of the licence that will be in force, following the callsign on the Station page as you type it.
- The licence's own **questions about the station**, as switches: in the UK, the one below.

In the UK, two more things to know before you transmit:

- **Station within 100 km of Charing Cross** (off by default). Ofcom's licence does not allow 431-432 MHz within 100 km of Charing Cross, London (Schedule 1 of the licence, the 431-432 MHz row of Tables A, B and C, for every class). The program does not work it out from your locator - a four-character square is too coarse near the 100 km boundary - so it asks: tick it if that is you, and any transmission reaching into 431-432 MHz is refused with that reason. The rest of 70 cm is unaffected.
- There is **no Notice of Variation setting yet**. The innovation bands - 70.5-71.5 MHz, 146-147 MHz and 2300-2302 MHz - need a Full licence *and* an NoV, so they are refused for every class, including Full, with that sentence.

The program never transmits at start, after a restart, after reconnecting to a radio, after you save Settings, after a band change or after recalling a memory. It comes up receiving, always.

## Choosing a radio

**Settings › Radio** (Ctrl + ,). Saving a change of radio restarts it; it comes back receiving.

**Simulator.** Simulated bands from 160 m to 6 cm, built from the band plan as you arrive on each: SSB nets, CW, FT8 at the band's dial, PSK and RTTY, the IBP beacons on 20 m to 10 m at the right minute of their cycle, static crashes on the low bands, and on 2 m and 70 cm FM simplex and real UK repeater pairs, each opening only to its CTCSS tone or a toneburst. Activity follows the time of day (Settings › Simulator can pin it to an hour). Its power is a Hermes-Lite 2's on HF (about 5 W) and a Pluto's above 30 MHz (4.5 mW), and it reports forward power and SWR from a simulated antenna on every band, so the SWR guard can be tried (Settings › Simulator › **Simulated antenna SWR**). Transmitting on it sends nothing anywhere - but the TX button still needs a licence class chosen and the licence box ticked, as with a real radio.

Whenever the simulator is the radio, a **SIMULATOR** badge sits beside *OpenHamShack Radio* at the top left, so its bands are never taken for the real ones; it goes as soon as a real radio is running. Hover over it to see why the simulator is in use. **Amber** with an *i*: Settings › Radio says Simulator (the default until you choose a radio), or `--device sim` was given on the command line for this run. **Red** with a warning triangle: the simulator is *standing in* for your radio, because the saved radio was not one OpenHamShack Radio knows or the settings file could not be read - it says which, once as a notice too. Choose your radio again in Settings › Radio. (A radio that is chosen but cannot be opened never falls back to the simulator: the radio stays stopped and the status line at the bottom says why.)

**Pluto family** - ADALM-Pluto, Pluto+, LibreSDR and Pluto nano are the same AD936x chip behind the same driver, so they are one choice. **Untested on hardware in OpenHamShack Radio.** Its **Pluto address** is a libiio URI:

- `ip:192.168.2.1` - a Pluto plugged in by USB (it is a USB network adapter as well as a radio). This needs no special USB permissions, so it is the one to try first.
- `ip:pluto.local` - the same by name, if `avahi-daemon` is running.
- `ip:<address>` - a Pluto+ or LibreSDR on your Ethernet, at the address your router gives it.
- `usb:<bus>.<device>.<interface>` - direct USB, which needs the udev rule from `libiio-utils`.

**Find** asks libiio for every Pluto it can see, then tries `ip:192.168.2.1` and `ip:pluto.local` directly, and lists what answered; pick one and it fills the address in. Then **Save**.

What a Pluto reaches depends on how its firmware identifies the chip:

- As an **AD9364** (the "AD9364 setting"), it receives from 70 MHz and transmits from 46.875 MHz, up to 6 GHz: 4 m, 2 m, 70 cm, 23 cm, 13 cm, 9 cm and 6 cm.
- As an **AD9363** (how many Plutos are shipped), it tunes only 325 MHz to 3.8 GHz: 70 cm, 23 cm and 13 cm. 4 m, 2 m and 6 cm are greyed on the band bar; click one and OpenHamShack Radio explains, and offers to change the setting for you (see [The AD9364 setting](#the-ad9364-setting)).
- **4 m** sits right on the receiver's 70 MHz floor. It is marked *experimental* (an amber dot on the band bar): how well it receives there is unmeasured.

**Sample rate** is 1.2 MS/s (the default) or 2.4 MS/s, shared by receive and transmit. 2.4 MS/s shows all of 2 m's busy part at once and is the Pluto nano's own rate; at 1.2 MS/s a nano runs at 2.4 and the program converts.

**LibreSDR** is a Pluto as far as OpenHamShack Radio is concerned: choose **Pluto family** (or **LibreSDR**, the same driver under its own name, which a controller lends by that name) and give it its Ethernet address (`ip:<address>`, from your router's device list).

**RTL-SDR (receive only)** and **SDRplay RSP (receive only)** are reached directly, without SoapySDR, on Linux, Windows and macOS. **Not yet tried on a real dongle or RSP.** The TX button stays locked with either: *This radio can only receive*.

- **RTL-SDR**: Linux needs `librtlsdr0` (the package recommends it; it also keeps the kernel's TV driver off the dongle). The Windows installer carries the library; the dongle itself needs the WinUSB driver once, fitted with Zadig (zadig.akeo.ie: Options › List All Devices, pick *Bulk-In, Interface (Interface 0)*, WinUSB, Replace Driver), or it reads as busy. It runs at 1.2 or 2.4 MS/s; automatic gain is the tuner's own, and a manual gain picks the tuner's nearest step.
- **SDRplay RSP**: needs **SDRplay's own API**, from SDRplay's installer at sdrplay.com - OpenHamShack Radio never includes it. Without it, Settings › Radio says *Install SDRplay's API to use this radio* under the choice. It runs at 2.4 MS/s whatever the sample rate says. Automatic gain is the API's AGC; a manual **Receiver gain** of G dB asks the RSP for 79 - G dB of gain reduction (held to 20-59). **RSP LNA state** is the RSP's own input attenuation, higher attenuating more (4 by default).
- **Receiver serial** picks one of several alike; empty takes the first found.

**Hermes-Lite 2** - 160 m to 10 m, about 5 W, over Ethernet. **Tested only against an emulator of the radio, never a real one.** With **Hermes-Lite 2 address** empty it is found by a broadcast on UDP port 1024 when the radio starts; a radio on another subnet needs its address (ip or ip:port). **Find**, under the address, sends the same broadcast now (and asks a typed address directly) and lists every radio that answered, with its gateware and MAC, and whether it is busy streaming to another program; picking one fixes the address to it. Leaving the address empty is usually better: a fixed address stops working when DHCP moves the radio. A radio that answers but cannot be used (gateware too old, not a Hermes-Lite 2) is listed with the reason. Nothing answering gets a sentence on what to check - power, the network, a firewall dropping UDP 1024 and 1025. Its receiver covers 0-38.4 MHz; it transmits only on 1.8-30 MHz, the range its N2ADR filters cover. **Hermes-Lite 2 rate** (192 kS/s by default) is its receive rate; 384 kS/s shows more of a band but costs twice the processor. **HL2 power amplifier** on gives about 5 W; off, the low-level RF1 output (up to 17 dBm - still enough to destroy a transverter input that wants 0 dBm). **Swap HL2 transmit I/Q** exists because whether the HL2 wants its transmit I and Q swapped is not documented: a wrong choice mirrors your signal, so USB comes out as LSB. Settle it on the first key-up with a known tone into a dummy load, watched on another receiver.

To try the Hermes-Lite 2 path with no radio, the emulator OpenHamShack Radio was tested against is in the package:

```
PYTHONPATH=/usr/lib/openhamshack-radio python3 -m ohscore.devices.hl2sim --port 11024
```

then set **Hermes-Lite 2 address** to `127.0.0.1:11024` and the radio to **Hermes-Lite 2**. It sends a test tone on 14.1 MHz.

**SoapySDR (receive only)**, Linux only: Airspy, HackRF and anything else with a SoapySDR module, and an RTL-SDR or RSP through theirs. **SoapySDR device** takes its arguments (`driver=rtlsdr`, `driver=airspy`); **Detect** lists what is plugged in. The TX button stays locked with this radio: *This device is receive-only*.

**Reference error** (ppm, Settings › Radio › Calibration) is your radio's crystal error, measured once against a signal you trust - a beacon, or a GPS-locked source - and applied to every tune. There is no automatic correction as there is on QO-100.

**Receiver gain control** (Slow AGC by default) and **Receiver gain** are the Pluto's own front-end gain; **HL2 receiver gain** is the Hermes-Lite 2's. All of them apply as soon as you save, without restarting the radio.

![Settings › Radio: the radio, the Pluto's address and Find, and the sample rate. The Hermes-Lite 2, with its own Find, and calibration are further down the page.](screenshots/settings-radio.png)

## The window

![The main window on the simulator, 20 m USB, Full licence: the Voice workspace.](screenshots/main-20m-usb-1920.png)

From the top:

**The header.** The frequency readout, the two status chips, the TX button, and four small buttons: second display, Settings, Logbook and Keyboard shortcuts. (In a small window the four become one button with them on a menu: see [Window sizes and text size](#window-sizes-and-text-size).)

- **The readout** shows the frequency you hear - the on-air frequency - in large figures, with the band above it (*20 M · MHZ*). The last three figures (the hertz) are small. When you transmit somewhere else - a repeater shift, split, XIT - a second line shows **TX** and that frequency (with the shift, for example *−0.600*); in repeater reverse it shows **RX** and where you are listening. Beneath are the **RIT**, **XIT**, **SPLIT** and **STEP** chips and the band-plan segment you are in, with its colour.
- **The licence chip** (*LICENCE · FULL*) says what your class may do where you would transmit: the power limit and the segment (*25 W PEP · FM simplex*). It is green where you may transmit, amber where the band plan objects or the power estimate is over your class's limit (you may still transmit, with a warning), and amber **NO TX HERE** where you may not - amber, because it is a frequency to move off, not a fault; red is kept for being on the air. Before you have chosen a class it reads *LICENCE · NOT CHOSEN* and amber **NO CLASS**: transmit is locked everywhere until you choose one in Settings › Licence & plan or the Welcome. Hover over it for the reason and the estimated power at your current drive.
- **The PTT sequence chip** says where the sequencer is: **RX** receiving, **SEQ** (the PA line is keyed, waiting before RF), **ON AIR**, **HANG** (RF off, waiting to drop the line), and which line it drives (*no PA line* when there is none).
- **TX**: the transmit button. See [Transmitting safely](#transmitting-safely).

**The band bar**, under the readout: the bands from 160 m to 6 cm that your radio can receive - a Hermes-Lite 2 shows 160 to 10, a Pluto 4 m and up - and a band reached through a converter. A band is bright where your class may transmit, dimmer with a small open ring where you may only listen, and faint where one Pluto setting would reach it (its tooltip says why). The band you are on is highlighted, with three dots under it for its band-stack registers. On the right: **FT8** and **FT4** (this band's dial frequencies), **A=B** and **A↔B** (the VFOs).

**The bandscope and waterfall** across what the radio's sample rate shows, with the band plan's segments along the top (hover over one for its limits and what it is for), markers for the IBP beacons and calling frequencies, your receive passband in blue, and where you would transmit as a dashed gold mark (red while you are on the air). Decoded FT8 callsigns and text-mode characters are written on the waterfall where they were heard; labels never overlap or run off the edge, and give way rather than crowd. How much of a band is shown depends on the rate: a band the span holds is shown whole; a wider one follows your dial.

**The zoom scope**, below on the left, is the few kHz around your frequency: your passband, its edges (drag them to set the filter), and in the digital modes the receive and transmit offsets (the transmit one gold while receiving, red on the air).

**The lower panel**, under a row of tabs that never moves: **Operate** (the panel for the current mode - see [Modes](#modes)), **Logbook**, **Memories**, **CW Activity** (see [The CW skimmer](#the-cw-skimmer-cw-activity)) and **Decoders** (see [Decoders on frequencies of their own](#decoders-on-frequencies-of-their-own); not on the tab row of the smallest window). The mode's name and one line about it (*FT8 · 15 s periods*, or, in amber, what the mode is missing on this computer) are the first line inside Operate. The **Workspace** button sits at the right end of the tab row (below).

**The rail** on the right: **Mode**, **Transmit** (drive, the power estimate, ALC/peak, forward power and SWR, PA temperature once the radio has reported one, the Tune button, and a warning line under the power estimate while there is something to warn about) and **Receive** (signal, SNR in the passband, volume and mute, AGC, gain with AGC off, the filter, the noise blanker and noise reduction, and the **Auto-tune** and **Best audio** buttons). How much of each card shows depends on the workspace. A compact **Receive** card is the signal, SNR, volume and mute and AGC, with a **▸ More receive controls** line that opens the rest in place (remembered for the workspace); a compact **Transmit** card is the drive, the power estimate and any warning, and the rest comes back while you are on the air.

- **The Mode card** groups the modes under three headings, always in the same order so a button stays where your hand learnt it: **Voice** (USB, LSB, CW, AM, FM, FreeDV), **Digital** (FT8, FT4, JS8, PSK31, PSK63, PSK125, RTTY) and **Pictures & data** (SSTV). The heading of the group you are in is in the accent colour. Where room is short (the Watch workspace, a smaller window) the card shows one button per group instead, labelled with that group's most recent mode: click it to choose that mode, or its arrow for the group's menu. **Ctrl + E** opens a menu of every mode, recent ones first, and takes type-ahead: *j* goes to JS8, *psk6* to PSK63.
- A mode with a small amber ring in its corner is missing something on this computer - hover over it, or choose it, to read what to install.
- **The Transmit card** shrinks to one line when this run cannot transmit - *Receive only this run* (started receive-only, or a receive-only SDR) or *Set up to transmit: Settings › Station*, with a button, while the licence box is unticked (on the simulator too). It never shrinks or hides while anything is on the air, while an over is armed, or while a transmit warning stands.

**The status strip** along the bottom: the radio (green dot running, red stopped, with the reason), **● REC** with the time and size while you record receive IQ (amber: red is kept for transmitting), its sample rate, the processor load (hover over it for how long the window takes to draw), **overruns** (times receive lost samples - a gap in the radio's stream, or the receiver more than two seconds behind; should stay at 0), your licence class (in amber, *no licence class: TX locked*, until you choose one), the reference correction if you have set one, the FM channel name, and the time in UTC. A smaller window drops some of these into the radio item's tooltip.

**Notices** slide in at the top centre over the scopes: blue for news, amber for a warning, red for an error. They go by themselves, stay while the mouse is over them, and a click dismisses one. Warnings about where and how hard you would transmit - a power estimate over your licence, a power that cannot be estimated, the band plan - are not notices: they are one line on the **Transmit** card, under the power estimate, which shows the most serious (the licence's power before the band plan), changes as you tune or move the drive, and goes when the condition does. A refusal, and anything that unkeys you, is still a notice.

**View › Light theme** (Ctrl + T) changes to a light theme. The window remembers its size and position.

### Workspaces

A **workspace** decides how much room each part of the window gets. There are three, and the radio, the band bar, the scopes' settings and every control are the same in all of them:

| | Digital | Voice | Watch |
| --- | --- | --- | --- |
| For | FT8, FT4, JS8, PSK, RTTY, and SSTV | USB, LSB, CW, AM, FM, FreeDV | looking at a whole band: who is where |
| Wide scope | a strip, a quarter of the height | 42 % of the height | two thirds of the height |
| Zoom scope | narrow and tall, never under 160 px | the biggest it gets | narrow |
| Rail | Mode in full; Transmit and Receive compact | every card in full, with the large S-meter | slim: Mode as group buttons, Receive compact, Transmit hidden while nothing transmits |
| Lower panel | Operate | Operate | CW Activity |

**Auto**, the default, follows the mode: Digital for the Digital and Pictures & data groups, Voice for the Voice group. Watch never comes by itself; you choose it.

- **The Workspace button** at the right end of the tab row says which is showing and whether it follows the mode (*auto*) or you chose it (*chosen*). Its menu, also **View › Workspace**, has **Auto - follows the mode**, **Digital**, **Voice**, **Watch** and **Reset this workspace's layout**.
- **W** steps to the next workspace (Digital, Voice, Watch) and keeps it; **Shift + W** goes back to Auto.
- **Choosing a mode** - a mode button, Ctrl + a number, Ctrl + E or the pad's MODE key - brings that mode's workspace and goes back to Auto, even from one you chose. Tuning from CW Activity, a memory or a click on a scope may change the mode but leaves the workspace alone, so browsing the band from Watch stays in Watch.
- Switching never changes the mode, the frequency, or anything about transmitting. Even in Watch, the Transmit card comes back in full while anything is on the air, an over is armed, or a transmit warning stands.

Drag the splitters between the scopes, the panel and the rail as you like: each workspace remembers its own, as proportions, so the same layout comes back in full screen or on a smaller screen. It also remembers which tab it last showed and which cards you opened. **Reset this workspace's layout** puts its defaults back.

### Window sizes and text size

The window may be as small as **1024 × 600**. It lays itself out in one of three sizes:

- **Full**, from 1500 × 860: everything as described above.
- **Compact**, from 1180 × 700: the header drops the program's name, keeping its icon; the readout's figures shrink to fit (never losing a digit); the rail narrows, with every card compact and the Mode card as group buttons; the status strip moves the sample rate and processor load into the radio item's tooltip.
- **Tight**, below that, down to the minimum: the header is one line, with the four small buttons on one three-dot menu; the rail is hidden, and **Controls** on the tab row opens it as a drawer over the right-hand side (never over the wide scope, where you tune); the current mode sits on a button beside it, with every mode on its menu by group. The scopes keep at least 120 px for the wide one (40 px of it waterfall) and 160 px for the zoom. In Tight, the drawer opens by itself once when a transmit warning comes up or you key with Space or the TX button, and **Controls** turns red while either holds. **Esc** while you are transmitting or armed always unkeys first; with nothing on the air it closes the drawer.

**Text size** - **Settings › Display › Text size**, 100 %, 115 % or 130 % - makes every word and figure in the window larger when you save. The window's sizes are worked out from its size divided by the text size, so larger text moves the window into a smaller layout rather than cutting words off, and the minimum grows with it (1332 × 780 at 130 %). A text size whose minimum would not fit your screen is greyed, and hovering over it says why. The FT8 list's own size (Ctrl + wheel over it) is on top of this.

![FT8 in a 1024 × 600 window: the Tight layout, with Controls and the mode button on the tab row.](screenshots/main-ft8-1024.png)

### Tuning

- **Click** a scope to tune there. In SSB the click is the dial; in CW the dial goes so the signal sounds at your CW pitch; in PSK and RTTY so it lands on the decoder; in FT8, FT4, FreeDV and SSTV the dial goes to a round frequency with the signal in the audio window.
- **Drag your passband** to tune by dragging. **Drag anywhere else** to pan the view. A **middle double-click** puts the view back.
- **The mouse wheel** over a scope steps the dial by the current step. **Ctrl + wheel** zooms the scope. Over a **digit** of the readout, the wheel tunes by that digit.
- **Left / Right arrow** step down / up; **Shift** makes it ten steps, **Ctrl** 1 Hz. **[** and **]** make the step smaller and larger (1, 10, 50, 100, 500 Hz, 1, 5, 6.25, 10, 12.5, 25 and 100 kHz), as do a click or the wheel on the **STEP** chip. Each mode has its own natural step - 50 Hz in SSB, 12.5 kHz in FM - chosen when you change mode.
- **F**, or a click on the big figures, opens the readout for typing. It takes `14.074` or `145.5` (MHz), `433500` or `7074` (kHz), `14074000` (Hz), or anything with a unit (`7074k`, `1.2965 GHz`). **Enter** tunes, **Esc** cancels. Anything outside 0.1 MHz - 6 GHz is refused with a sentence.
- **RIT** (R) moves only what you hear, **XIT** (X) only where you transmit. The wheel over either chip sets its offset and turns it on.
- **SPLIT** (S) transmits on VFO B. **A=B** on the band bar copies A to B; **A↔B** swaps them.

### Adjusting a scope

The **Adjust** button in the top-right corner of each waterfall (just its slider glyph in a Tight window) opens that scope's adjustments, titled *Adjust the wide scope* or *Adjust the zoom scope*, in three tabs. The wide and the zoom scope each keep their own; the second display's big scope shares the wide scope's. Everything takes effect as you move it and is remembered.

- **Scope**: **Automatic scale** (the default) follows the noise floor; turn it off for a fixed **Top** (dBFS) and **Range** (dB), which start from where the automatic scale was, so nothing jumps. The dB labels follow. **Smoothing** averages the trace over time, from **raw** (each spectrum line as it comes) to 1 s; the default, 0.13 s, is the look it has always had. The waterfall and the peak ghost are not smoothed. **Display style**: **Standard** draws the scope's own fine bins, so a carrier or an FT8 tone stands at its full level and a wide signal, such as a data mode or SSB, reads its power per narrow bin and looks low beside them; **SDR Console-like** widens the resolution bandwidth to about 100 Hz and gives the trace a short hang and decay, so wide and narrow signals stand at about the relative heights SDR Console shows them. The waterfall follows the style. It changes only the picture: no reading or meter changes with it. The resolution bandwidth the trace is drawn at is written in the frequency axis, after its unit ("RBW 18 Hz", for example). **Colours…** opens Settings › Display at the scope colours.
- **Peaks**: **Peak hold** draws a faint ghost over the trace at each frequency's recent maximum. **Hold peaks for** Off, 1 s, 1.5 s (the default), 3 s, 10 s or ∞ (until cleared), **then fall at** 1-60 dB a second (default 10). **Clear peaks** starts the ghost again from the trace. **Label the strongest signals** (off by default) writes the frequency and level over up to **At most** signals (1-10, default 5) that stand **Over the noise by** at least 3-40 dB (default 10). The frequency is written as the axis writes it, in MHz ("14.0745  -62"). One signal gets one label, however wide; labels are chosen twice a second and a label stays while its signal does, so they do not flicker or swap places.
- **Waterfall**: **Automatic levels** (the default, following the noise floor), or a manual **Floor** and **Contrast range**; the **Speed** (¼× to 2×); and the **Palette**.

They are on the scope because you adjust them while looking at the signal. The waterfall's levels, speed and palette are also in Settings › Display.

## Bands and band stacks

Click a band on the band bar to go there. Each band keeps **three registers** - dial, mode, filter, AGC, and in FM the repeater shift and CTCSS tone - and a band you return to comes back as you left it. **Click the band again** (or press **V**) to step to its next register; the dots under the button show which one you are on. **B** and **Shift + B** go to the next and previous band your radio can reach.

A band's first visit depends on the mode you are in when you click it. From a digital mode (FT8, FT4, PSK, RTTY, WSPR) it lands on the band's FT8 dial - FT4's from FT4 - for example 14.074 FT8 on 20 m. From anything else it lands at the start of the band plan's SSB segment in the band's sideband, LSB below 10 MHz and USB above (USB on 60 m, as UK practice is): in the UK 3.603 LSB on 80 m (3 kHz into the segment, so your voice is inside it), 7.053 LSB on 40 m, 14.125 USB on 20 m. A band with no SSB segment, 30 m, starts on its FT8 dial. The other two registers are the band's other usual places - on 20 m from SSB, 14.074 FT8 and then 14.025 CW.

Some bands are on the bar but behave differently:

- **6 m** has no radio here on its own. The Hermes-Lite 2 stops at 38.4 MHz and the Pluto cannot receive below 70 MHz, so it is not on the band bar. No built-in memory leads there, and if you type a 6 m frequency the licence chip reads **NO RADIO** in grey rather than showing your licence's limit, because the guard refuses the band whatever the licence allows. Set a 6 m transverter for it in Settings › Converters (a 28 MHz IF on the Hermes-Lite 2) and it becomes an ordinary band ([Converters](#converters)).
- **4 m** is experimental on a Pluto (above).
- **60 m** is Full-licence only, in the eleven UK segments (see the licence table under [Transmitting safely](#transmitting-safely)).

## Converters

A band can be worked through a **transverter** or an up/down-converter instead of directly: 23 cm from a Pluto on a 2 m IF, 2 m or 6 m from a Hermes-Lite 2 on 28 MHz, HF through an upconverter in front of a receive-only SDR. **Settings › Converters** holds the list, like SDR Console's Converter Definitions, and under it which band uses which.

Each converter has a **Title**, a **Type** - **Down** when the radio sits below the air frequency (a transverter), **Up** when above (an HF upconverter) - a **Use**: **RX only**, **TX only** (one you only transmit through; its TX offset is required, and it is named by what it does on transmit, so one fed from below the air frequency is an **Up-converter**) or **RX/TX**, an **RX offset** and a **TX offset** (shown in Hz, typed in MHz; a transverter's offset is its local oscillator: 116 MHz for 144 MHz on a 28 MHz IF), **Inverted** for a high-side local oscillator, whose spectrum is mirrored (OpenHamShack Radio converts both ways), and its **Most drive** in dBm. The edit form shows what it does as you type: *144-146 MHz on air appears at 28-30 MHz on the radio*. **Add**, **Copy**, **Edit** (or double-click), **Delete** and **Up**/**Down** work on the selected entry; one a band uses cannot be deleted. **+ VHF/UHF/SHF** adds common transverters (50 and 144 MHz on 28; 432 on 28; 1296 and 2304 on 28 or 144; 3400 and 5760 on 144) and two HF upconverters; where each value comes from is in docs/converters.md.

**Bands**, under the list, sets each band to **Direct** or a converter. Through one:

- the dial, the band bar, the log and the memories stay on the air frequency; the readout's second line shows **IF** and what the radio itself is tuned to;
- the **licence and band-plan guard judge the air frequency**, never the IF: 1296.2 MHz through a 2 m IF is 23 cm to the guard, so a Foundation licence is refused there even though 144.2 MHz would be fine;
- a band the radio cannot reach - 2 m or 6 m on the Hermes-Lite 2 - is on the band bar whenever the radio reaches the converter's IF for it; the tooltip says which converter;
- a band set to a **TX only** converter is received directly - the radio tunes the band itself - and transmitted through the converter;
- only an **RX/TX** or **TX only** converter transmits, and only once its **Most drive** is entered - from its manual; transverters typically want 0 dBm or less. OpenHamShack Radio will not save a band that transmits through one without it, and the Drive slider's ceiling on that band becomes the drive at which the radio's full output meets it (with a Hermes-Lite 2's 5 W and 0 dBm, about 1.4 %). The ceiling follows the frequency you **transmit** on: receiving on 20 m with split set to 144.3 MHz holds the drive under the 2 m transverter's limit. If you have measured your radio's output and entered it as **Device W** on Bands & power, the limit uses that when it is higher than the radio's own figure; a radio that does not say what it puts out refuses to transmit through a converter until you enter it. Nothing can raise the drive past the limit while keyed - the slider, Tune, a changed setting - and changing a converter in Settings while an over waits for its slot unkeys it if the new one cannot take it. A Hermes-Lite 2 with its **power amplifier on** refuses to transmit through a converter that takes 0 dBm or less: turn the PA off in Settings › Radio and restart the radio first (until the restart the PA is still on, and it is still refused) - even its low-level output (17 dBm) is fifty times too much, so check the drive into a dummy load before connecting the transverter;
- a transverter's gain goes in **PA gain** on Bands & power, so the power estimate covers it. Until it is entered, the transmit card says **Power at the antenna unknown** instead of showing the radio's own milliwatts, and its warning line says *transverter output not entered*; it warns and does not refuse. The radio's forward-power reading is the transverter's input, so it is never held to the licence limit there.

The PTT sequencer does not yet switch a separate line or relay per transverter; it keys its one line for every band.

## Receiving

Choose your radio and a band, and the bandscope fills. Then tune. Everything you hear is what the radio receives, corrected only by the **Reference error** you entered; there is no beacon lock.

The **Receive** card on the rail has **Volume** and **Mute** (M), **AGC** (Off, Fast, Med, Slow), **Gain** with AGC off, the **Filter low / high** edges (also by dragging the passband's edges on the zoom scope; , and . narrow and widen it), the **Noise blanker** (N) for impulse noise, and **Noise reduction** (Shift + N) with its **NR strength** for steady hiss, then **Auto-tune** (A) and **Best audio** (Shift + A) (both below).

### The line at the centre (DC)

An RTL-SDR, an SDRplay RSP or a Pluto puts a steady line of its own at the exact centre of what it receives. Radio takes it out (Settings › Radio › **DC spike removal**: *Automatic* does so for those radios, and not for the Hermes-Lite 2 or the simulator, which make none), and never lets the centre come near what you are listening to: tune onto it and the receiver moves instead.

### The S-meter

The **Signal** meter at the top of the **Receive** card has three styles and four units.

- **Bar**, the default: the figure at the top right, a bar beneath with a peak marker that holds for a moment and falls.
- **Analogue**: a needle meter. The scale is printed for the unit you chose (S1 to S9 then +20, +40, +60 for S-units). The section beyond S9 is drawn plain while you receive - a loud station is not a danger - and turns red only while you are on the air. A thin amber **peak-hold needle** follows the highest recent reading and falls back after a second and a half; switch it off from the meter's menu or Settings.
- **Digital**: a large readout with a slim bar under it, and a second figure at the right (dBm beside S-units, the S reading beside dBm, the dBFS level beside the relative units).

**Click the meter** to go to the next style; **click the reading** (the figure at the top right, or the unit name in the digital style) to go to the next unit. **Right-click** for a menu with both, the peak-hold needle, **Calibrate…** and, once there is one, **Forget this calibration**. Your choice is remembered. The same choices are in **Settings › Radio**, under *S-meter*.

The meter rises at once and falls with a half-second time constant: the ballistics IARU Region 1 recommends for S-meters.

Units:

- **dBFS**, the default: the power in the receive passband against the radio's full scale. It is exactly what the meter always showed.
- **S-units** (S1 to S9, then S9+10, S9+20...) and **dBm**, by IARU Region 1's recommendation: S9 is **−73 dBm below 30 MHz** and **−93 dBm from 30 MHz up**, and one S-unit is 6 dB. (Which applies follows the dial: on 160 m to 10 m it is −73 dBm, on 6 m and up −93 dBm, and the analogue dial's face says which.)
- **dB over noise**: the passband against the noise that would be in it with no signal, estimated from the zoom scope's spectrum (the same floor the *SNR in passband* meter uses). 0 means only noise.

#### Calibrating the S-meter

The radio reports levels in dBFS; turning that into dBm needs an offset that depends on the radio, its gain. Until there is one that holds, **S-units and dBm carry an amber UNCAL mark**. They still move with the signal - on a nominal 0 dBFS = 0 dBm - but the numbers mean nothing yet; hover over the meter for the reason.

To calibrate: set **Receiver gain control** to **Manual** (Settings › Radio) (the Hermes-Lite 2 has only its **HL2 receiver gain**, which always counts as known), put a signal of known level in the receive passband - best, a signal generator through a known attenuator into the antenna socket - and choose **Calibrate…** from the meter's menu (or the button in Settings › Radio). It shows the level it measures (an average of the last three seconds); type the signal's level as dBm (`-93`), an S reading (`S9`, `S9+20`) or microvolts (`5 uV`), and **Calibrate**. You can also type the offset itself in Settings › Radio.

- The calibration belongs to **this radio** **on this band** - a radio's gain differs by more than an S-unit between bands, so 2 m and 70 cm are calibrated separately, and between bands there is nothing to calibrate. A different radio, or the same Pluto at a different address, starts uncalibrated.
- It remembers the receiver gain it was made at, and a later change of **Receiver gain** or **HL2 receiver gain** is allowed for, dB for dB, so you need not recalibrate after turning the gain. For the best accuracy, calibrate at the gain you use.
- With the receiver's **own AGC** on (Slow or Fast AGC) its gain moves with the signal and nobody knows it, so S-units and dBm go back to UNCAL until it is Manual again. The simulator is the exception: its AGC choices are a fixed gain.
- The figure is for the signal in the passband, as wide as the filter: a carrier from a signal generator reads its own level; a wide signal partly outside the filter reads less.

FM has its own squelch, in the FM panel: see [FM, repeaters and CTCSS](#fm-repeaters-and-ctcss).

### Noise reduction

**Noise reduction** (Shift + N, or the switch beside the noise blanker on the **Receive** card) takes the steady hiss out of what you hear, between words most of all. It is the "NR2" of Thetis, piHPSDR and linHPSDR - Warren Pratt's (NR0V) noise reduction from the WDSP library, ported - and it learns the noise by itself: give it a second or so after switching on, or after tuning somewhere with a very different noise level.

- **NR strength** (under the switch, and in Settings › Audio) is how far it may pull the noise down: **0 %** leaves the audio untouched, **50 %** (the default) up to 20 dB, **100 %** up to 40 dB. Higher takes more noise out but makes weak syllables sound thinner; most signals sound best between 40 and 70 %.
- It works in **USB, LSB, CW, AM and FM**, on what you hear. Decoders - CW, PSK, RTTY, FT8/FT4, SSTV and FreeDV - always get the audio without it, whatever the switch says: they decode better from the untouched passband. In the digital modes the speaker is untouched as well.
- It is **off by default**. Switching it fades over a twentieth of a second, so it never clicks, and it does not disturb the AGC.
- It adds **45 ms** of delay to what you hear while it is on.
- A **steady carrier** (a tune-up whistle, a beacon's unkeyed carrier) held for more than a second or two is, to a noise reduction, part of the noise floor, and fades with it. Keyed CW and speech come through.
- It is not a noise blanker: crashes and clicks are the **Noise blanker**'s (N) job, and the two work together.

### Auto-tune and best audio

Two buttons under the noise controls on the **Receive** card, for SSB voice (USB and LSB). Each listens to the station on the dial for **four seconds**, then acts once - the button reads *Listening…* meanwhile - and the line beneath says what it did, or why it did nothing.

**Auto-tune** (A, or right-click the signal on either scope and choose *Auto-tune onto the voice here*) puts the dial exactly on the other station's suppressed carrier, so the voice sounds right. Click anywhere on the station, or just below it (USB) or above it (LSB), and let it find the rest. If several stations are near, it takes the one whose voice spans the dial.

- SSB has no carrier to lock to, so it uses the voice. The spectrum shows where the station's speech starts, which is about 300 Hz from its carrier; that gets within a hundred hertz or two. Then the pitch harmonics finish the job. Voiced speech is a row of evenly spaced tones, and they sit where they should only when the dial is right. Over a few syllables at different pitches, only one setting of the dial fits them all.
- On the simulator it lands stations within 6 Hz on both sidebands, from 6 dB to 20 dB SNR (half the time within 1 Hz). It **refuses rather than guesses** when it cannot be sure: silence, a carrier, CW, beacons and data modes (PSK, FT8, RTTY, multi-tone modems - anything whose level holds steady), someone holding one long vowel, a station more than 2.5 kHz from the dial, or a capture where the first and second two seconds do not agree. It says which, as *Auto-tune refused: …*. If the station paused, press again while they talk.
- It moves the **dial**, so you then transmit where they are, which is how a QSO is netted. With **RIT** on, it moves RIT instead and leaves your transmit frequency alone.
- What it corrects is the difference between the two stations: their transmitter's error and your receiver's together.
- It measures; it does not track. If the station drifts, press it again.

**Best audio** (Shift + A) measures the station on the dial and sets the receive filter, AGC, noise reduction and noise blanker for it, in one go. The line under the buttons gives what it measured and chose. The button's tooltip gives the reason for each choice. The rules are plain:

| Setting | Rule |
| --- | --- |
| Noise reduction | **Off** at 20 dB SNR and over: a strong signal has nothing to lose but the edges of its speech. Below that, on: 30 % from 12.5 dB, 50 % from 7.5 dB, 70 % under that. |
| Filter | 50 Hz below the speech heard to 100 Hz above it, within 100–2900 Hz. Under 10 dB SNR the top stops at 2500 Hz, under 6 dB at 2300 Hz, where a weak voice is only hiss. |
| AGC | **Slow** on a weak signal (under 20 dB), so the gain holds through pauses instead of lifting the noise between words. **Medium** on a strong one. **Fast** when there are impulses. |
| Noise blanker | **On** when impulses (samples over the blanker's threshold, counted on the wide signal) come twice a second or more. Otherwise off. |

SNR here is the station's speech peaks against the noise in the band it occupies, which reads a few dB higher than an average would. It is applied **once**: change anything afterwards and your setting stands until you press it again. If the station paused while it listened, or the dial is on a beacon or a data signal, it changes nothing and says so.

## Modes

Choose a mode on the rail's Mode card, with Ctrl + a number, or from the **Ctrl + E** menu, which has every mode (see [Keyboard shortcuts](#keyboard-shortcuts)). The **Operate** panel underneath changes with it, and the window changes to the mode's workspace unless you chose one yourself ([Workspaces](#workspaces)). Picking FT8, FT4, JS8 or CW also tunes to that band's usual dial, unless you are already near it - **Tune to usual frequency on mode** (Settings › Station) turns this off; it never changes band.

### USB, LSB and AM

The **Microphone** card: **Mic gain**, **Compressor** (0 is off), the microphone level while you transmit (peaks in the amber, never the red), and **Monitor** to hear yourself, with its level. **Transmit audio** sets the low and high edges of what you send (300-2700 Hz by default). Both edges of your signal are what the guards judge, so SSB dialled just inside a band or segment edge can still be refused: LSB on 1850.5 kHz puts speech below 1850 kHz, where the licence's limit is different.

**AM** transmits here (unlike in OpenHamShack QO-100 NB): full carrier, modulation held under 90 % both ways, so the carrier never pinches off however hot the microphone, and the carrier is about a quarter of the PEP, as for any AM transmitter. The occupied width is twice the audio's, and the Transmit audio edges apply to AM too. The licence's limit is on PEP, and the power estimate is PEP.

AM is held 6 dB below the radio's full output: at the same **Drive** its PEP is a quarter of what SSB's is, and the power estimate shows that. This is deliberate. A receiver hears AM's envelope, so any squashing at the very top of a transmitter's range goes straight into the audio, where SSB and FM are not hurt by it - and a stock Pluto sounded terrible in AM at full scale while its FM and SSB were fine. Set Drive for the PEP you want; the amplifier after the radio supplies the watts. If AM still sounds rough, try less Drive before anything else.

An AM receiver must be tuned to your carrier within a few hundred hertz. A radio whose crystal is a few ppm out is several kilohertz off on 70 cm, enough to put the carrier at the edge of the other station's AM filter and garble the audio of a strong signal. Set **Reference error** (Settings › Radio › Calibration) first.

### FM, repeaters and CTCSS

![2 m FM on the simulator: repeater RV57, its −600 kHz shift, the tone to send and the tone heard.](screenshots/main-2m-fm-repeater-1920.png)

The **Repeater** card shows the channel name (RV53, V40, RB4 …) and the output and input frequencies. **Shift**:

- **Auto** (the default) follows the repeater pairs of the band plan in force - or of your country, where OpenHamShack knows them without a whole plan. Where neither is known, Auto is simplex: a guessed direction would put you on another repeater's output. In the UK it follows the UK channel plan: on a repeater output it transmits on that repeater's input, on a simplex channel on the same frequency. It knows 2 m RV48-RV63 (−600 kHz), 70 cm RB0-RB15 (+1.6 MHz - the UK's 70 cm repeaters listen *above* their output, the reverse of the IARU plan), RU65-RU78 (+7.6 MHz), the 9 MHz DV pairs (−9 MHz), 23 cm RM0-RM15 (−6 MHz) and 10 m RH1-RH8 (−100 kHz).
- **Simplex** transmits where you listen.
- **−** and **+** transmit that far below or above where you listen, by the **Offset for − and +** under them, in MHz. Arriving in a band sets it to the band's usual split in the plan in force - in the UK 100 kHz on 10 m, 600 kHz on 2 m, 1.6 MHz on 70 cm, 6 MHz on 23 cm (the RSGB band plan); IARU Region 1's 7.6 MHz on 70 cm - and you can type any other: **5** for an RBW repeater (outputs 433.000-433.375, inputs 5 MHz up), or whatever a non-standard repeater uses. A band's stack remembers the offset with the rest of the register, so going back to 70 cm finds the 5 MHz you left there. Auto ignores it.

**Reverse** listens on the repeater's input (and transmits on its output) - to hear whether you could work the other station direct. The readout's second line shows what you are doing: **TX 145.062 500 −0.600**, or **RX … reverse**.

**1750 Hz** (or **T**, in FM) sends a toneburst for the time set in Settings › Transmit & safety (500 ms): on its own if you are not transmitting - it keys, and the guards apply, as for any transmission - or at the start of your over if you are. Many UK repeaters still accept it, but it is being withdrawn in favour of CTCSS, so it is a button, never automatic.

The **CTCSS** card: **Send** is the tone sent with your transmission, **Tone squelch** opens the receiver only for that tone. Both are wheels: scroll, use the arrow keys, or click either half. Tones show their UK letter (G 103.5 Hz is common in central Scotland). **Heard** shows the tone on the signal you are receiving, or *carrier* or *squelched*; **Send the tone heard** copies it to Send. The tone is sent at 12 % of peak deviation by default (Settings › Transmit & safety; no UK recommended figure was found).

**Receive & audio**: **Squelch** (0 is open), **Channel and deviation** - 12.5 kHz channels with 2.5 kHz deviation (the UK standard) or 25 kHz with 5 kHz - and **Mic gain**.

The guards judge the frequency you **transmit** on, so with a shift it is the repeater's input that must be inside your licence and not in the satellite sub-band; changing the shift, the offset or Reverse while transmitting is checked like moving the dial, and unkeys if the new input would be refused. FM on HF below 29 MHz draws a band-plan warning (the plan puts HF FM at 29.6-29.7 MHz).

![Transmitting into a simulated repeater: the tone came back, the sequencer chip reads ON AIR, the power is an estimate.](screenshots/transmitting-fm-repeater-1920.png)

### Voice memories

Up to six recorded messages - a CQ, a contest exchange, "QRZ?" - sent with **F1** to **F6** in USB, LSB, AM, FM and FreeDV, or with their buttons in the **Voice keyer** row of the Operate panel. **Radio › Voice memories…** (or **Edit…** on the row, or a right-click on a button) names them, records them and imports them:

- **Record** records from your microphone - the one in Settings › Audio, through the radio's own sound stream, so it is what your PTT would send - with the level meter above; **Stop** ends it (it stops by itself after two minutes, or when you transmit). Set your **Mic gain** first and record at the level you speak at: what is kept is the microphone itself, before mic gain and the compressor, so your mic gain still applies when it is sent.
- **Play** plays it to your speaker. It does **not** transmit.
- **Import WAV…** takes a WAV file from anywhere (16-bit PCM is safest; any rate, stereo is mixed to mono), up to two minutes.
- **Clear** empties the slot. The name field is what the button and the transmit card call it.

Sending one keys exactly as your PTT would and goes through the same microphone chain - mic gain, compressor, transmit filter - and **every transmit check**: your licence class (none chosen: nothing transmits), the band plan, the PTT sequencer, the power chain and the converter limits, and the repeater shift in FM, with your CTCSS tone. A memory that would be refused is refused with the same sentence as PTT. The transmit card says **Sending voice memory 2: CQ contest** while it goes, and the over ends by itself at the end of the recording. A memory longer than the transmit time-out is refused before it starts. Dead air does not apply to it (it ends by itself); the time-out and the watchdog do.

**Repeat** on the row sends it again and again - a CQ loop - with the pause between calls set in the editor (10 s by default; the transmit card counts it down). **Any PTT press, Esc, tuning (a click on a scope, a memory, a band or mode change) or turning Repeat off stops it**; so does any refusal or emergency unkey. Repeat is never remembered: OpenHamShack Radio always starts with it off.

The recordings are kept as `keyer/voice-1.wav` … `voice-6.wav` in the data folder (`~/.local/share/openhamshack-radio/keyer/` on Linux, `%APPDATA%\openhamshack-radio\data\keyer\` on Windows; names in `keyer/voice.json`), so you can copy them to another computer.

### CW

Type in the line under the terminal and press **Enter**: the keyer sends it at **Speed**, at your **Pitch**. **As you type** sends each word as you finish it. **Stop** (or Esc) empties the queue and unkeys. **Space** (or the TX button) in CW sends a steady carrier at your pitch, for tuning up. The decoder writes what it reads into the terminal and on the waterfall. The **QSO** fields fill in the macros - your CW memories - `{MYCALL}`, `{CALL}` (or `{DXCALL}`, the same: their call), `{RST}` and `{LOC}` (your locator); **F1** to **F8** send the macros from the keyboard while the Operate panel is showing; a macro whose field is empty is not sent, and says what to fill in; **Edit** changes them. There is no paddle input, and on the Hermes-Lite 2 keyboard CW is sent by the program, not the radio's own CW generator, yet.

### The CW skimmer (CW Activity)

**CW Activity** in the lower panel (Ctrl + K) decodes every CW signal in the CW segment of the band the dial is in, all at once, whatever mode and frequency you are listening to - as CW Skimmer does. Switch it on with **CW skimmer** at the top of the view (or Settings › Station); it is off until you do, because it takes a share of a processor core while it runs (about half a per cent for each signal it decodes).

- **Spots** lists each call it has heard and checked: when it was last heard (UTC), its frequency, speed, signal-to-noise in 500 Hz (as the Reverse Beacon Network measures it), its country, and **CQ**, **DX** or **BEACON**. Every signal is read by two decoders at once - a neural one and the classic one - and a call counts when either prints it. A call is listed as soon as it is read, but is grey with a **?** until it has been read twice and is on Radio's list of active callsigns (the calls the Reverse Beacon Network heard in a recent week, plus Super Check Partial's MASTER.SCP if you have it), or three times if it is not on the list. **By frequency** sorts it as a band map, **Newest** by time.
- **Signals** lists the channels it is decoding now, strongest first, each with the text it is reading.
- The spots are marks along the foot of the wide scope (**Marks on scope** turns them off), and each newly confirmed call is labelled on the waterfalls.
- **A click on a spot, a signal or a mark tunes there in CW.** It only tunes: nothing in CW Activity ever transmits or answers a call. **Clear** empties the list, not the skimmer.
- It follows the band the dial is in and never retunes the radio. If the receiver's span does not reach the band's CW segment (10 m, a Hermes-Lite 2's narrow span), the view says so.
- Spots stay on this computer: nothing is sent to the Reverse Beacon Network or anywhere else.
- The **Watch** workspace opens on CW Activity, with two thirds of the window for the wide scope ([Workspaces](#workspaces)).
- **Settings › Station › CW skimmer**: the squelch (how far over the noise a signal must stand to be decoded), how many signals it decodes at once (64; up to 256 for a contest), and **Download MASTER.SCP**: on, Radio also fetches Super Check Partial's list of contest callsigns from supercheckpartial.com into its data folder when the skimmer starts, at most once a day. It is not part of Radio because nothing allows passing it on. Off (the default), Radio still uses a copy you put there yourself.

### PSK31, PSK63, PSK125 and RTTY

The same terminal, typing line, queue and macros as CW. The decoder listens at 1000 Hz in the audio; **Signals** lists the carriers in your passband and clicking one tunes it onto the decoder. Clicking a signal on a scope does the same. The RTTY mode is 45.45 baud, 170 Hz shift; other speeds and shifts are a decoder's in the Decoders view (below).

### Decoders on frequencies of their own

**Decoders** in the lower panel (Ctrl + Shift + D; on a small window, View › Decoders) runs decoders that each listen on a frequency of their own, whatever the dial and the mode are doing - several RTTY stations at once beside the one you are working, say, or an SSTV frequency while you work RTTY. **Add** starts one: the decoder, its frequency in MHz (for RTTY the middle of its two tones, for SSTV its 1900 Hz leader; empty takes where the dial puts the mode's signal), and the decoder's own choices: RTTY's speed (45.45, 50 or 75 baud), shift (170, 425, 450 or 850 Hz) and reversed; SSTV's mode (any, or one of Martin M1/M2, Scottie S1/S2/DX, Robot 36/72, PD50 to PD290) and whether to start a picture joined part way. **Right-click a signal on a scope › Decode here as** starts one on it without the view. Each gets a card with what it copies - for SSTV the picture painting in as it arrives with that decoder's recent pictures beside it (click one to look at it); **Tune** puts the dial on it in that mode, **Stop** ends it. They only listen.

While a decoder runs, Radio holds the receiver's span still for it - the stretch the wide scope shows, which then says *Span held for decoders* and marks each decoder's frequency. You tune freely inside it and the decoders carry on undisturbed; anything the scope shows beyond it is greyed. Tuning outside it - the knob, a click, a band button, a memory - asks first (*Tuning to 7.0500 MHz stops: RTTY on 14.0933 MHz. Continue?*): **Yes** stops those decoders and the receiver follows you again, **No** leaves everything as it was. Playing a DAB station asks the same, since DAB takes the receiver to Band III. A decoder added too far from the dial to fit in one span with it is refused, with a sentence saying so. When the last decoder stops, the receiver follows the dial again. They start again with the radio. Up to four run at once, sharing at most a quarter of one processor core; past that the newest pauses until there is room (Settings › Decoders). The mode's own decoder is never paused, and shows in the view too while the mode is RTTY or SSTV.

### Broadcast FM, DAB and the station lists

**WFM** plays a broadcast FM station in stereo when it sends its pilot, with **RDS**: the station's name appears large beside the frequency, with **STEREO** while the pilot is heard, and what it says it is playing (its RadioText) under the name. Hover over the name for its programme identification and type. Every retune starts the receiver again, so the last station's name never stays on the new frequency. **De-emphasis** (Settings) is 50 µs in Europe and most of the world, 75 µs in the Americas.

**Stations** in the lower panel (Ctrl + Shift + S; on a small window, View › Stations) lists the FM and DAB stations Radio can hear. FM is one line per programme, by name or by frequency, filtered to one programme type if you like; a station heard on several frequencies is listed once, on its strongest, with the others under **Also on**, and one without RDS by its frequency. **Click** a station to listen: WFM on its strongest frequency. The DAB list has every station of every ensemble found; a click plays it (a DAB station takes the receiver until you stop it, as in Decoders).

Radio makes these lists by itself, **once a week, at night** (03:00 by default), but only while nobody is using it: nothing changed for half an hour, no broadcast station playing out loud, not transmitting, recording or decoding. Busy, it tries the next night. **Scan now** makes them at once (about a minute and a half at 2.4 MS/s; DAB needs 2.048 MS/s or more). A scan moves only the receiver, never your dial, and the moment you touch anything it stops and everything is as you left it. Settings › Decoders › Station lists has the hour, how often, how long Radio must have been left alone, and the switch to stop the nightly scans.

### FT8 and FT4

![FT8 on 20 m in the simulator, at the band's FT8 dial.](screenshots/main-ft8-20m-1920.png)

Decoding uses OpenHamShack Radio's own decoder, a port of WSJT-X 2.7.0's `jt9` that found exactly what `jt9` found on hours of real slots; where it is missing (the `all` package) or fails, WSJT-X's `jt9` decodes instead if WSJT-X is installed, and where both are there `jt9` checks every slot. No package carries WSJT-X: on Windows and macOS it is used only if you install it yourself, and nothing is missing without it. The panel says which is decoding (*decoder: ohsdigi* or *jt9*, under band activity); **Settings › Station › FT8 and FT4 decoder** can put `jt9` first. Sending uses OpenHamShack Radio's own encoder, a port of WSJT-X 2.7.0's that makes the same signal bit for bit (the `all` package uses WSJT-X's `ft8code`/`ft4code` instead); a message WSJT-X could not send - a report of +99, say - is refused with a sentence saying why. **FT8** and **FT4** on the band bar put the dial on this band's FT8 or FT4 frequency (WSJT-X's defaults: 14.074, 7.074, 144.174 MHz and so on); a band with none listed says so. These modes bring the **Digital** workspace, where the band activity takes most of the window. The panel is OpenHamShack QO-100 NB's: **Band activity** lists the decodes slot by slot (UTC as 15:38:45), messages to you and your own overs in gold, with each sender's country by its short name (the full name when you hover) (from the `cty.dat` OpenHamShack Radio carries, or a newer one from [country-files.com](https://www.country-files.com/) put in its data folder), **click a line** to answer that station, **Tx1 … Tx6** are the standard messages, **Auto seq** moves through the QSO and logs it when complete, **Hold TX freq** keeps your transmit offset still, **TX = RX** keeps it on your receive offset, Ctrl and the mouse wheel over the list change its text size, and on the zoom scope a click sets the receive offset (Shift + click only the transmit one).

The guards judge your actual tone, not the dial. The UK 60 m FT8 dial is 5357 kHz, but the 5354-5358 kHz segment ends 1 kHz above it: answer a station above 1 kHz in the audio and the transmission is refused, because it would leave the segment.

**The pile-up line**, above the band activity when there is a pile-up, says who it is on (the station in your DX call, or else the one with the most callers over the last two slots of one period, at least two), how many are calling and the strongest few with their reports, and where you stand: *you: not calling*, *you: calling* or *answered you*, and *working …* when they answered someone else. Click it to put that station in the DX call; nothing is sent, and not while Enable TX is on. **Halt TX** is a plain button that turns red while Enable TX is on or anything is on the air.

FT8 depends on your computer's clock being right to within a second (on Linux, `timedatectl` should say *System clock synchronized: yes*).

### JS8

JS8 is JS8Call's mode: free text typed to a station, sent as a run of frames, one per period. Choosing JS8 tunes to the band's JS8Call dial (14.078 MHz on 20 m, 7.078 on 40 m, and so on), unless the dial is already there. The panel has its own **JS8 band activity** - UTC, dB, DT, Freq, Speed, From and Text - where each message's frames are joined back into one row, growing as they arrive. **Only to me** shows just the messages to your callsign; **Heartbeats** shows or hides the automatic *@HB* heartbeats. All five JS8 speeds (Slow 30 s, Normal 15 s, Fast 10 s, Turbo 6 s, Ultra 4 s) are decoded at once.

To send: type a callsign and text, or *CQ*, in the **Send** card, or use **CQ**, **Heartbeat** or **Reply** (a message to the station picked in the list), then **Send**. That queues the message and turns **Enable TX** on: its frames go out one per period from the next period, at the speed chosen on the speed buttons (Normal unless you choose another; not changeable while a message is going out). Each frame is an over like an FT8 one and passes every licence and band-plan check. **Enable TX** off, **Halt TX** or **Esc** stops it, cutting a frame on the air. It needs your callsign in Settings › Station.

### Reporting what you hear to PSKReporter

[PSKReporter](https://pskreporter.info/) maps who is being heard where. OpenHamShack Radio can add what it decodes, as WSJT-X does - **off unless you turn it on**: **Settings › Station › Report stations heard to PSKReporter**. It needs your callsign and locator set on the same page, and refuses to turn on without them (every report says who heard it and where).

- **What goes**: for each station decoded in FT8 or FT4 whose message carries a callsign - its call, the frequency, mode, signal report, the slot's time and, if the message had one, its grid - with your callsign, locator and *OpenHamShack Radio* and its version. Nothing else: no audio, no log, nothing about the computer.
- **The frequency** is the on-air one: the dial plus the signal's audio offset. With a converter or transverter in use, that is the air side (1296.2 MHz, not the 144 MHz IF), as the dial shows it.
- **When**: in one batch every five minutes or so, as PSKReporter asks, and each station once per five minutes. Decodes marked low-confidence (WSJT-X's `?`), calls the decoder could only show as `<...>`, and your own call are not reported.
- **Off again** drops whatever was waiting, unsent. Closing the program sends what was waiting.
- If the Internet is down the reports are simply lost; it never interrupts you to say so (the program's log notes it, once an hour).

### FreeDV

FreeDV needs `libcodec2`. Choose **700D**, **700C**, **1600** or **2020**; the ones your codec2 cannot open are greyed. The card shows **SYNC** when the modem has locked, the modem SNR, and the text channel. Talk with Space or the TX button as in SSB.

### SSTV

Received pictures paint line by line as they arrive, in any of fourteen modes - Martin M1 and M2, Scottie S1, S2 and DX, Robot 36 and 72, and PD50, 90, 120, 160, 180, 240 and 290 - from the picture's header, or from its line syncs when you tuned in part way through (it says *joined part way*). They are saved in Radio's data folder and the **Gallery** shows them; the oldest go once there are more than **Pictures kept** (Settings › Decoders, 100; pictures from earlier versions are left alone). To send one, choose the mode under the gallery - Robot 36, Martin 1, Scottie 1 or PD 120 - then **Send a picture…**.

## Transmitting safely

Transmit is locked until you have ticked the licence box (the Welcome, or Settings › Station). After that, every key-up - Space, the TX button, Tune, the toneburst, a CW line, an FT8 message - and every change of dial, split, shift, mode or filter while keyed passes the same checks. OpenHamShack Radio **refuses** to transmit, and says why on the TX button, on the licence chip and in a notice, when:

- the radio is not running, or is receive-only;
- you have not chosen a licence class yet (*No licence class chosen*);
- your licence class does not have the frequency, or the signal would reach past the edge of an allocation it has;
- it is an innovation band (no NoV setting yet), or 431-432 MHz with **Station within 100 km of Charing Cross** ticked;
- the signal would reach a beacon or satellite sub-band of the band plan;
- the band plan objects and **Band-plan guard** is set to **Enforce**;
- the band has no radio here (6 m), or the radio cannot transmit there (the Hermes-Lite 2 above 30 MHz, a Pluto below 46.875 MHz);
- the PTT sequencer's line could not be opened, or the SWR guard has tripped and not been acknowledged.

Power is not on that list. When the power chain's **estimate** is over your class's limit, OpenHamShack Radio **warns** - the licence chip turns amber, the Transmit card's warning line says *Estimate over the licence limit: transmitting is not refused*, in amber, with the full sentence in its tooltip (*Foundation licence: 25 W PEP maximum on 144.0-146.0 MHz, and the power chain's estimate is 64 W. An estimate, so a warning, not a refusal*) - and transmits. The estimate is numbers you typed, and can be wrong in either direction. Where the radio **measures** its own output, the limit is enforced on the measurement instead: see [Power](#power-drive-the-power-chain-and-the-estimate).

It judges both edges of the signal, never the dial.

### The licence guard (always on)

In the UK the limits are Ofcom's amateur licence conditions (Schedule 1, Tables A, B and C, published 21 February 2024), as OpenHamShack Radio holds them. Every row was checked against Ofcom's PDF on 4 October 2026 (the record, with the PDF's checksum and page of each row, is `docs/ham/licence-check.md` in the source); no figure in the power table was wrong. Ofcom changed the licence in February 2024 and again in October 2025 - check against the current conditions yourself.

| Band | Foundation | Intermediate | Full |
| --- | --- | --- | --- |
| 160 m 1810-1850 kHz | 25 W | 100 W | 1000 W |
| 160 m 1850-2000 kHz | 25 W | 32 W | 32 W |
| 80 m | 25 W | 100 W | 1000 W |
| 60 m (eleven UK segments) | - | - | 100 W PEP and 200 W EIRP, 6 kHz wide at most |
| 40 m | 25 W | 100 W | 1000 W |
| 30 m | 25 W | 100 W | 400 W |
| 20 m, 17 m, 15 m, 12 m, 10 m | 25 W | 100 W | 1000 W |
| 6 m 50-51 MHz | 25 W | 100 W | 1000 W |
| 6 m 51-52 MHz | 25 W | 100 W | 100 W |
| 4 m 70.0-70.5 MHz | 25 W | 100 W | 160 W |
| 2 m | 25 W | 100 W | 1000 W |
| 70 cm 430-432 MHz | 25 W ERP | 40 W ERP | 40 W ERP |
| 70 cm 432-440 MHz | 25 W | 100 W | 400 W |
| 23 cm 1240-1325 MHz | - | 100 W | 400 W |
| 13 cm 2310-2350, 2390-2400 MHz | - | 100 W | 400 W |
| 13 cm 2400-2450 MHz | 2 W | 100 W | 400 W |
| 9 cm 3400-3410 MHz | - | 100 W | 400 W |
| 6 cm 5650-5680, 5755-5765, 5820-5830 MHz | 2 W | 100 W | 400 W |
| 6 cm 5830-5850 MHz | - | 100 W | 400 W |

Watts are PEP at the antenna unless marked. "-" means the class may not transmit there. Never allowed, for any class: 2350-2390 MHz, 13 cm above 2450 MHz, 3410-3475 MHz, and the innovation bands (70.5-71.5, 146-147 and 2300-2302 MHz) until there is an NoV setting.

The limits are **per sub-allocation**: a signal that touches two rows is held to the tighter one. Where the limit is ERP or EIRP (430-432 MHz, 60 m), the power chain's **antenna gain** is used to turn PEP into ERP or EIRP. The airborne 500 mW limit is not applied - OpenHamShack Radio is not an airborne station.

The sentences it gives are short and say which rule: *Foundation licence: 1270.0-1325.0 MHz is not available*, *60 m is open only to Full licensees*, *70.5-71.5 MHz is an innovation band: it needs a Full licence and a Notice of Variation*, *431-432 MHz may not be used within 100 km of Charing Cross (Ofcom licence, Schedule 1, Tables A-C, 431-432 MHz); Settings › Licence & plan says this station is*.

![A Foundation licence on 23 cm: the licence chip amber, NO TX HERE, and the TX button locked.](screenshots/main-23cm-foundation-refused-1366.png)

### The band-plan guard

The RSGB 2026 band plan (updated January 2026) is a code of practice, not law, so by default (**Warn**) a transmission outside what its segment is for goes ahead with an amber chip and, on the Transmit card's warning line, *Band plan: SSB is not what the CW segment (144.025-144.1 MHz) is for. Transmitting is not refused: the band-plan guard is set to warn.* - there before you key, so you can move first. Segment bandwidths count too (200 Hz in the HF CW segments, 500 Hz in the narrow ones, 2.7 kHz elsewhere on HF). **Enforce** refuses instead; **Off** says nothing.

Whatever it is set to, **beacon and satellite sub-bands are always refused**: the IBP beacon slots (14.100, 18.110, 21.150, 24.930, 28.200 MHz), the VHF/UHF beacon sub-bands, and the exclusive satellite sub-bands (10 m 29.300-29.510 MHz, 2 m 145.806-146.000 MHz, 70 cm 435-438 MHz). A repeater's own output is "not for transmitting" in the plan, so transmitting simplex on one draws a warning.

### Power: drive, the power chain, and the estimate

**Drive** on the Transmit card is how hard the radio is driven, as a share of its full output (25 % by default). Under it, the estimate: *≈ 281 µW PEP at the antenna (estimate) · 4.5 mW at full drive · licence 25 W PEP*. Power goes as the square of drive, so 50 % drive is a quarter of full power.

The red mark on the Drive slider is the band's **ceiling** (Settings › Bands & power), and the slider cannot pass it; lowering a ceiling lowers your drive by itself, and says so. Your licence's power limit does **not** hold the slider: when the estimate at your drive is over the limit, the Transmit card's warning line says, in amber, *Estimate over the licence limit: transmitting is not refused*, and the licence chip turns amber; both have the full sentence in their tooltip.

**Measured power is enforced.** Where the radio reports its forward power - the Hermes-Lite 2, and the simulator - and the band's chain has no PA gain entered, that reading is held to your class's limit (converted to ERP or EIRP with the antenna gain where the limit is one of those). If it is over on two readings in a row, the program unkeys at once, as the SWR guard does, and says what was measured and roughly what drive would meet the limit (*Unkeyed: Full licence: 200 W EIRP maximum on 60 m (measured 988 W EIRP). Lower Drive (about 11 % meets it)*). It is not latched: lower the drive and key again. The reading is taken as the power at the antenna, without subtracting the feeder loss you entered, so an entered number can only make the check stricter. With a PA gain entered, the radio's sensor sees the PA's input rather than the antenna, so on that band the limit is an estimate again and only warns. A Pluto measures nothing: its power is always an estimate.

**Settings › Bands & power** holds the chain, one row per band:

| Column | Meaning |
| --- | --- |
| Device W | What the radio puts out at full drive. Empty: the radio's own figure - a Pluto about 4.5 mW, the Hermes-Lite 2 about 5 W. Enter what you have measured. |
| PA gain dB | Your amplifier's gain (0: none, the radio barefoot). |
| Feeder loss dB | Loss between the amplifier and the antenna. |
| Antenna dBi | Antenna gain, used only where the licence's limit is ERP or EIRP. |
| Ceiling % | The most drive any control may set on this band. |
| At full drive | The estimate at 100 % drive, as you type. |

![Settings › Bands & power: the power chain per band. Empty Device W means the radio's own figure.](screenshots/settings-power.png)

An example: a Foundation licensee on 2 m with a Pluto (4.5 mW) into a PA with 40 dB of gain. At full drive that estimates 45 W; the limit is 25 W, so above 74 % drive the Transmit card and the licence chip warn that the estimate is over. Nothing stops the drive there: measure the PA's output and set the band's ceiling where it should be.

**Every number here is an estimate**, and the power warning is only as good as what you enter. The Pluto's 4.5 mW is one published measurement at 2.4 GHz; how much less it gives at 145 MHz or 5.7 GHz is unmeasured. A real PA does not follow drive squared once it starts to compress. Measure the chain into a dummy load with a power meter, band by band, and enter the measured **Device W**. A band with no chain entered transmits at the radio's barefoot power, and the estimate is only as right as the radio's own figure.

**Tune** on the Transmit card sends a steady carrier at reduced drive - **Tune drive** (Settings › Transmit & safety, 25 %) times your current Drive, so with Drive at 40 % the carrier goes out at 10 % - for an ATU or a PA's tune; the guards apply as to any transmission. Because it is a share of Drive, it can never be more than the drive you have set, which the band's ceiling holds down.

### Keying

**Space** or the **TX** button transmits in USB, LSB, AM, FM and FreeDV. In **Hold to talk** (the default) you transmit while it is held; in **Toggle** (Settings › Station) one press keys and the next unkeys. In CW, Space sends a carrier. FT8, FT4, JS8, PSK, RTTY and SSTV send from their own panel.

Off the air, the TX button says in a few words how this mode transmits: *Space to talk* (voice), *Enable TX below* (FT8, FT4, JS8), *Type, Enter sends* (CW, PSK, RTTY) or *Send from the panel* (SSTV). When a key-up would be refused it says why instead, as briefly - *Choose a licence class*, *Not on your licence*, *Not on this band*, *Power over the limit*, *SWR tripped*, *Sequencer not ready* - with the whole sentence when you hover over it. *Set up to transmit*, with a padlock, means the licence box is unticked (on the simulator too): Settings › Station fixes it, and the Transmit card shrinks to one line meanwhile. *Receive only* means a run started receive-only or a receive-only SDR; the QSO card's **Halt TX** is then hidden while nothing is on the air, and the control pad's HALT key is dimmed - but it still halts. **ARMED** with *next over in N s* means a timed over is waiting; nothing is on the air yet, and a click, Esc or Halt TX stops it.

**Esc always stops**: it unkeys at once and throws away anything queued to send, and stops a voice memory's CQ loop ([Voice memories](#voice-memories)).

While transmitting, the TX button reads **ON AIR**, with the time on air, the time left before the time-out and a bar counting down; a red glow frames the window; the readout turns red; receive audio is muted.

A transmission stops by itself:

| After | Default | Set in |
| --- | --- | --- |
| The **transmit time-out** | 5 minutes | Settings › Transmit & safety |
| **Dead air**: a voice mode with no sound from the microphone | 3 seconds | same |
| The **watchdog**: the window stopped responding | 2 seconds | same |
| **SWR** above the limit, where the radio measures it | 3.0:1 | same |
| **PA temperature** above the limit (Hermes-Lite 2) | 50 °C | same |
| The Hermes-Lite 2's TX-inhibit input | at once | - |
| The radio stopping or being unplugged | at once | - |
| Moving the dial (or split, shift, XIT, mode, filter) so that the signal would be refused | at once | - |

### The PTT sequencer

A PA, a mast-head preamp's bypass relay or a transverter switch needs its PTT line keyed **before** RF and released **after** it. **Settings › PTT sequencer**:

- **PTT line**: **None** (the default - nothing to switch) or **Serial RTS/DTR**, a USB-serial adapter's RTS or DTR line (or both), set by the program without any extra package.
- **Serial port**, e.g. `/dev/ttyUSB0`, and **Line**.
- **Sequence delay** (25 ms): on key-up, the line goes on, then this wait, then RF from zero drive; on key-down, RF stops and the radio's buffer drains, then this wait, then the line drops. RF never starts before the line has been on for the delay, and the line never drops while RF can still be coming out. Keying cancelled during the wait (Esc, the watchdog) drops the line again with no RF at all.

When the program stops for any reason - including a crash - the port closes and both lines drop, so the PA is left unkeyed.

**The glitch on opening.** On Linux, *opening* a serial port raises RTS and DTR for an instant before any program can clear them. OpenHamShack Radio opens the port once, when the radio starts, and clears both at once - a pulse of well under a millisecond, with no RF, which a relay does not follow. If your PA keys on the slightest glitch, drive it through an inverter with a pull-down. The Settings page says the same.

![Settings › PTT sequencer.](screenshots/settings-sequencer.png)

The Hermes-Lite 2's own open-collector outputs, Raspberry Pi GPIO and the Pluto's GPO pins are not drivers yet.

### SWR and temperature

Where the radio measures forward and reflected power - the Hermes-Lite 2, and the simulator's simulated antenna - the Transmit card shows **Forward** and **SWR** while keyed, and the program unkeys when the SWR, averaged over about a third of a second so SSB peaks do not trip it, stays above **SWR limit**. After a trip the card shows **SWR tripped: acknowledge**, and transmit is refused until you press it - check the antenna first. The Hermes-Lite 2 itself has no SWR fold-back; this is the only protection.

On the Hermes-Lite 2 the program also unkeys above **PA temperature limit** (50 °C, below the radio's own 55 °C cut-out). Once the radio has reported a temperature (it is read while transmitting), the Transmit card shows **PA temperature**, with the limit as a red mark; it keeps the last reading after the over, since a PA cools slowly and how hot it still is matters for the next one. With a Pluto the meter never appears. The Hermes-Lite 2's forward-power reading is on a provisional curve until calibrated against a meter, and is certainly wrong at low power.

**A Pluto measures neither.** With a Pluto there is no SWR or temperature protection at all: that is your PA's job.

### Before you key a Pluto into anything

The Pluto was designed as a lab instrument, and OpenHamShack Radio has not yet been checked on one. Before any PA or antenna:

- **It has no output filter.** Its harmonics (290 MHz from 145 MHz, for example) come straight out. Do not assume a PA's own filter is enough: nobody has measured what a Pluto puts out under OpenHamShack Radio, so how much a filter has to remove, and where, is not known. The check below comes first; what it shows decides whether a PA's filter will do or an external low-pass filter is needed as well. Never connect a bare Pluto to an antenna.
- **LO leakage.** The Pluto's transmit LO leaks a carrier. OpenHamShack Radio puts the LO a quarter of the sample rate below your signal - 300 kHz at 1.2 MS/s, 600 kHz at 2.4 MS/s - so the leakage is not on your own channel; but on 2 m or 70 cm that can put it on somebody else's, and a PA amplifies it. How strong it is, is unmeasured.
- **Check it first - this is the gate before any PA**: transmit into a dummy load and look at the output on a spectrum analyser - the leakage carrier, the image, the harmonics. Then into the PA and a dummy load with a power meter, to fill in the power chain. Only then an antenna.

## Logbook

**Logbook** in the lower panel (Ctrl + L, or the book button in the header). FT8 QSOs log themselves; everything else goes in with **Log a QSO**: call, reports sent and received, name, grid and comment. The frequency, mode and time come from the radio, and the ADIF band (20m, 2m, 70cm …) from the frequency. Click a call to open its page on QRZ.com in your web browser (a portable call such as EA8/G4ABC/P opens G4ABC). Double-click a cell to correct it. **Delete** removes the selected rows. **Export ADIF** (also **File › Export log as ADIF…**) writes an `.adi` file. The log is shared with OpenHamShack QO-100 NB and any other OpenHamShack app on this computer (below).

![The logbook.](screenshots/logbook-1920.png)

## Sharing the logbook with a controller

The logbook and the station profile (callsign, locator, country, licence and class) are kept once per computer and shared by every OpenHamShack app on it: QO-100 NB and Radio on one laptop keep **one** log, and a contact logged in either appears in both. Logs from before this version are moved in the first time it starts; the old file is kept beside it as `log.jsonl.migrated`.

If you run an **OpenHamShack controller** on your network, **Settings › Controller** joins it: **Find controllers** lists the ones on your network (or type its address), then sign in with your controller user name and password (and the code from your authenticator app, if your account has one) and press **Pair**. From then on the logbook and station profile are kept in step with the controller and every other app paired with it, in both directions. If the two logbooks belong to different callsigns, you are asked whether to **merge** them or to **use the controller's** (this computer's is then kept as a file). The page shows how the sync is going.

Nothing needs the controller: with it switched off or out of reach the app logs exactly as before, and catches up when it is back. **Unpair** stops the sharing and keeps every contact and the profile on this computer. Your password is used once, to pair, and never stored.

## The control pad (Ajazz AKP03E)

An **Ajazz AKP03E** (USB 0300:3002: six keys with pictures, three small buttons, three knobs) works OpenHamShack Radio without the mouse: the knobs tune, set the volume and step through bands, the keys change mode, mute, record and step size. Plug it in and it is used at once; nothing needs setting up. If several OpenHamShack apps are open, the pad belongs to the one you last clicked in.

**Close the Ajazz or Mirabox "Stream Dock" software first**, including from the system tray by the clock. Windows lets both programs open the pad, and then the two fight over its keys and pictures.

**Transmitting from the pad is off until you allow it.** K1 is PTT (hold to transmit) unless you move it, but until **Settings › Control pad › The pad may transmit** is ticked and saved, the PTT key shows *PTT off* and pressing it keys nothing. When it is on, the PTT key goes through every check the TX button makes (licence, band plan, locks), and the transmitter stops at once if the pad is unplugged or the program stops answering it.

**Changing what the controls do.** **Settings › Control pad › Keys and knobs** has one row for each key (K1 to K6, top left to bottom right), each small button (B1 to B3) and each knob (D1 to D3, left to right) - turned, and pressed - with a list of what that control can do in Radio. Keys and buttons offer the presses, knobs the turns; a key can also do one step of a knob's job (*Tune up one step*, *Next memory*, *Volume down*...). **Nothing** is allowed anywhere. The pictures on the keys follow your choices. Changes take effect when you press **Save**; **Cancel** leaves the pad as it was, and **Reset to defaults** puts back the layout below. As shipped:

| Control | Does |
| --- | --- |
| K1 | PTT (hold to transmit) |
| K2 | Mute |
| K3 | Record |
| K4 | Next mode |
| K5 | Next band |
| K6 | Stop transmitting |
| B1 | Next tuning step |
| B2 | Nothing |
| B3 | Next page (only useful with pages set up on a controller) |
| D1 | Volume; pressed: mute |
| D2 | Tune; pressed: next tuning step |
| D3 | Band; pressed: nothing |

**Next mode** steps through the modes in the Mode card's order, group by group (Voice, then Digital, then Pictures & data), and brings the mode's workspace as a mode button does. While you record, the **Record** key reads *● ON* in amber, as REC does in the status strip: on the pad, too, red is only for transmitting.

Besides those, a control can be set to **Noise reduction on/off**, **Filter width** (a knob: the high edge in SSB, the width in CW and AM; the digital modes' and FM's filter is fixed), **Transmit power** (the drive, 2 % a detent) or **Memories**.

**PTT** can only go on one of the six keys with a picture (the key that shows *ON AIR* while you transmit), and only on one: choosing it for another key moves it there, and K1 then does nothing until you give it something else. Set it to **Nothing** on every key and the pad cannot transmit at all; the page says so. Moving PTT never changes the rule above: it still keys only once *The pad may transmit* is on, through every check, and stops when the pad is unplugged. While you are transmitting, Save refuses to move or remove the PTT key, so the key you are holding always stops the transmission.

Your choices are kept with the station profile, so they survive updates and, with a controller paired, follow you to the controller's pad. A choice this version cannot use (an action that has gone, a setting from a newer version) puts that one control back to its default rather than doing something else.

**Settings › Control pad** says whether the pad is found and working and, if not, why, in words: another program has it, no permission (Linux), unplugged, a model this version does not drive. **Test controller** lights each key in turn; then press every key and button and turn every knob, and each one is listed on the page. Nothing reaches the radio during the test. **Copy controller report** puts a short report on the clipboard (what is plugged in, which part of it the program opens, what the installation has for it, the problems seen): paste it into an email to the developers. It holds no callsign, locator or passwords. From a terminal, `openhamshack-radio --pad-report` prints the same report without opening the window.

On Linux the `.deb` installs the udev rule that lets you open the pad without root; it takes effect at once. The AppImage cannot install it: if the page says *no permission*, run once
`echo 'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0300", ATTRS{idProduct}=="3002", MODE="0660", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/60-openhamshack-pad.rules && sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw`
and plug the pad in again.

Only the AKP03E's second revision (0300:3002) is driven. The first AKP03E (0300:1002), the AKP03 and AKP03R and Mirabox's N3 are recognised and named in the report, but not used: the first AKP03E, for one, never reports a key being let go, so a held PTT could not end.

## Memories

**Memories** in the lower panel (Ctrl + B). Click one to go to its frequency and mode; **Alt + 1** to **Alt + 9** recall the first nine from anywhere. **Save current** stores where you are, under a name. The built-in ones are the band plan's centres of activity - QRP and QRS CW frequencies, the UK emergency frequencies on 80 m and 60 m, the SSTV frequencies, the 2 m and 70 cm FM calling channels and APRS, the narrow-band centres from 2 m to 6 cm - and each band's FT8 dial. Recalling a memory never transmits.

## Second display

A separate window for another screen - a big waterfall with the frequency large across the top, or the mode panel at reading size. **Ctrl + D**, the screen button in the header, or **View › Second display** opens and closes it; Settings › Second display chooses the screen and what it shows. In HAM its status line shows the band, the mode and the CTCSS tone, coloured as the licence chip.

## Settings

**Settings** (Ctrl + , or the gear) has eleven pages. Nothing in Settings can key the transmitter. **Save** applies everything at once or, if anything is out of range, nothing, and says what; **Cancel** throws the changes away. A change to the radio, its address or rate, the sequencer's line or the simulator restarts the radio, which comes back receiving.

The licence class, the power chain, the ceilings, the timers and the radio itself can only be changed here, never from the main window, so a stray key can never raise a limit.

Besides the settings listed below:

- **Station** also holds the **licence** tick box, the same one as the Welcome's. Unticked, OpenHamShack Radio receives only, on the simulator as well as a radio.
- **Bands & power** is the power chain table, described under [Power](#power-drive-the-power-chain-and-the-estimate).
- **Converters** is the converter list and the converter for each band ([Converters](#converters)).
- **Audio** also has **Noise reduction** and its strength ([Noise reduction](#noise-reduction)), and chooses the **Microphone**, **Speaker** and an optional **Second output** (receive audio for other software), with **Listen to the microphone** and **Play a test tone**. **System default** says which device it means now, such as *System default (USB Audio CODEC)*: on Linux the name your sound settings use where PipeWire or PulseAudio will say it (otherwise their own word, *default* or *pulse*), on Windows the device Windows' sound settings call the default. *(none found)* means the system has no microphone, or no speaker, at all. Plugged something in, or changed the default, with Settings open? **Look again** lists the devices afresh, keeping what you had chosen.
- **Radio** also has the **S-meter**: its style, its units, the peak-hold needle, and the calibration offset for the radio and band in use, with **Calibrate…** ([The S-meter](#the-s-meter)).
- **Display** also chooses the **theme**, the **text size** (100 %, 115 % or 130 %: see [Window sizes and text size](#window-sizes-and-text-size)), the **waterfall palette**, the waterfall **levels** and its **speed**. The **scope colours** are there too: presets **Classic** (the original look), **Amber**, **Green phosphor** and **High contrast**, or **Custom**, with a colour for the trace, the fill under it, the peak ghost, the peak markers, the grid and the background, the trace width (1-3 px), the fill on or off and its opacity, the grid's opacity, and **Reset to default**. A preview shows the choice before you save. They apply to every scope, the second display's too, in both themes (the scopes are dark in the light theme as well).
- **Second display**: open it, which screen, full screen, and what it shows.

![Settings › Licence & plan.](screenshots/settings-licence.png)

The table below is generated from the Settings window itself (`tools/settings-ref.py --app ham`), so its labels and sentences are exactly what the window shows. The station's country and the licence controls (licence, class, station questions, your own licence) are described under [the Welcome](#the-first-time-it-starts) and not repeated in it.

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
| Report stations heard to PSKReporter | On / Off | Off | Send the callsigns you decode in FT8, FT4 and JS8 to PSKReporter every five minutes: their call, frequency, mode, signal report and grid, with your callsign, locator and this program's name. |
| CW skimmer | On / Off | Off | Decode every CW signal in the band's CW segment at once, whatever the dial is on, and spot the calls it hears. Receive only; the spots stay on this station. |
| CW skimmer squelch | 3.0 dB – 20.0 dB | 6.0 dB | How far over the noise a CW signal must stand to be decoded by the skimmer. A signal is followed once it stands this plus 2 dB over the floor. |
| CW skimmer channels | 8 – 256 | 64 | The most CW signals the skimmer decodes at once, strongest first. Each takes about half a per cent of one processor core. |
| Download MASTER.SCP | On / Off | Off | Also download Super Check Partial's list of contest callsigns (MASTER.SCP) from supercheckpartial.com once a day while the skimmer runs, so more calls are spotted after two decodes instead of three. Radio already carries a list of calls the Reverse Beacon Network heard recently. Off: a copy you put in the data folder is still used. |

#### Radio

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Radio | Simulator / Pluto family / LibreSDR / Hermes-Lite 2 / RTL-SDR (RX only) / SDRplay RSP (RX only) / SoapySDR (RX only) | Simulator | Which radio. The simulator (HF and VHF/UHF bands, busy with other stations) needs no hardware and is the default. An RTL-SDR or an SDRplay RSP only receives; an RSP needs SDRplay's own API installed. *Restarts the radio when saved.* |
| Pluto address | text | `ip:192.168.2.1` | libiio URI: ip:192.168.2.1 (Pluto over USB), ip:pluto.local, ip:<address> (Pluto+, LibreSDR), usb:<bus>.<dev>.<n>. *Restarts the radio when saved.* |
| SoapySDR device | text | `driver=rtlsdr` | SoapySDR device arguments for a receive-only SDR, e.g. driver=airspy. *Restarts the radio when saved.* |
| Sample rate | 1.2 MS/s / 2.4 MS/s | 1.2 MS/s | Pluto sample rate. 1.2 MS/s suits a Raspberry Pi; 2.4 MS/s shows all of 2 m's busy part at once and is the Pluto nano's native rate (at 1.2 MS/s the nano runs at 2.4 and the program converts). *Restarts the radio when saved.* |
| Receiver gain control | Manual / Slow AGC / Fast AGC | Slow AGC | Receiver gain control in the SDR. |
| Receiver gain | 0 dB – 73 dB | 40 dB | Receiver gain when gain control is manual. |
| Hermes-Lite 2 address | text | (empty) | Empty: found by broadcast when the radio starts. Find lists what answers now; pick one to fix its address. A radio on another subnet: type its address, and Find asks it directly. *Restarts the radio when saved.* |
| Hermes-Lite 2 rate | 48 k / 96 k / 192 k / 384 k | 192 k | Hermes-Lite 2 receive rate. 192 kS/s covers the busy part of any HF band at a sixth of a Pi's budget for 384 kS/s. *Restarts the radio when saved.* |
| HL2 receiver gain | -12 dB – 48 dB | 20 dB | Hermes-Lite 2 receiver gain (the AD9866's LNA). |
| HL2 power amplifier | On / Off | On | Hermes-Lite 2 power amplifier (about 5 W). Off: the low-level RF1 output, up to 17 dBm - still enough to destroy a transverter that wants 0 dBm. *Restarts the radio when saved.* |
| Swap HL2 transmit I/Q | On / Off | Off | Swap the Hermes-Lite 2's transmit I and Q. Whether HL2 clients swap them is not documented; a wrong choice mirrors the signal (USB comes out as LSB). Settle it with a known tone into a dummy load. *Restarts the radio when saved.* |
| Receiver serial | text | (empty) | The RTL-SDR's or SDRplay RSP's serial number, to pick one of several alike. Empty: the first found. *Restarts the radio when saved.* |
| RSP LNA state | 0 – 27 | 4 | The SDRplay RSP's LNA state: higher attenuates more. 4 suits an HF dipole in the evening; the range each band allows is in SDRplay's API notes. *Restarts the radio when saved.* |
| RSP DAB notch | Automatic / On / Off | Automatic | The SDRplay RSP's DAB notch (about 160-230 MHz), ahead of its LNA: keeps a strong Band III transmitter from overloading the receiver wherever it is tuned. Automatic: in, except while the receiver is tuned within 174-240 MHz or a DAB station plays. On or off holds it. RSPdx, RSP1A, RSP1B and RSPduo only (not the RSPduo's Hi-Z input); on any other radio, the RSP2 and RSP1 included, it does nothing. |
| RSP broadcast notch | Automatic / On / Off | Automatic | The SDRplay RSP's broadcast notch, ahead of its LNA: one switch for the FM band (about 77-115 MHz) and MW (about 500-1530 kHz). Automatic: in only while the receiver is tuned below 60 MHz, except within the LW and MW broadcast bands; out above 60 MHz, because in it costs at least 4 dB on 2 m (SDRplay's RSPdx figure). On holds it in everywhere: for a station near a strong FM transmitter. Off holds it out. RSPdx, RSP1A, RSP1B, RSP2 and RSPduo (on Tuner 1's Hi-Z input, that port's MW notch); on any other radio, the RSP1 included, it does nothing. |
| Reference error | -50.00 ppm – 50.00 ppm | 0.00 ppm | The device's reference error, measured once against a known signal; applied to every tune. |
| DC spike removal | Automatic / On / Off | Automatic | Take out the line a receiver's own DC offset puts at the centre of the span. Automatic: on for the Pluto family, RTL-SDR, SDRplay and SoapySDR receivers, off for the Hermes-Lite 2 and the simulator. |

#### Decoders

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Decoders at once | 0 – 16 | 4 | How many decoders may run on frequencies of their own, beside the mode's decoder. *Restarts the radio when saved.* |
| Processor share for decoders | 5 % of a core – 100 % of a core | 25 % of a core | The share of one processor core the decoders may use between them. Past it the newest is paused until there is room; the mode's own decoder is never paused. *Restarts the radio when saved.* |
| Pictures kept | 1 – 2000 | 100 | How many received pictures to keep. Past it the oldest are deleted. |
| Weekly station scan | On / Off | On | Make the FM and DAB station lists by itself: once a week, at night, while nobody is using the radio. It gives the radio back the moment anyone does, with everything as it was. |
| Scan at (hour) | 0 h – 23 h | 3 h | The hour of the night (local time) the weekly station scan is tried. Busy then, it tries the next night. |
| Scan every | 1 days – 60 days | 7 days | How old a station list may be before the night's scan makes it again. |
| Only after idle for | 1 min – 720 min | 30 min | How long the radio must have been left alone (nobody tuning or listening) before a night's scan may start. |

#### Licence & plan

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Band plan | Follow the country / RSGB 2026 / IARU Region 1 / IARU Region 2 / IARU Region 3 | Follow the country | The band plan shown and checked. auto: the station country's national plan where one is written, else its IARU region's. |
| Band-plan guard | Warn / Enforce / Off | Warn | Warn: a transmission outside what its segment is for goes ahead with a warning. Enforce: it is refused. Beacon and satellite sub-bands are refused whatever this says. |

#### Transmit & safety

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Tune drive | 5 % – 50 % | 25 % | Drive for a tune carrier (an ATU or PA tune), as a share of your current Drive: at 25 % with Drive at 40 %, the carrier goes out at 10 %. |
| SWR limit | 1.5:1 – 5.0:1 | 3.0:1 | Unkey when the measured SWR stays above this (devices that measure it: HL2, simulator). |
| PA temperature limit | 30 °C – 60 °C | 50 °C | Unkey when the PA is hotter than this (HL2: below the gateware's own 55 °C cut-out). |
| Toneburst length | 100 ms – 2000 ms | 500 ms | Length of a 1750 Hz toneburst. |
| CTCSS level | 5 % – 25 % | 12 % | CTCSS tone level as a fraction of peak deviation (10-15 % is common practice; no UK figure was found). |
| Transmit time-out | 0:10 min – 30:00 min | 5:00 min | Unkey after this long transmitting. |
| Dead-air unkey | 1 s – 30 s | 3 s | Voice modes: unkey after this long with no microphone audio. |
| UI watchdog | 0.5 s – 10.0 s | 2.0 s | Unkey if the user interface stops servicing the engine for this long. |
| TX audio low edge | 50 Hz – 1000 Hz | 300 Hz | - |
| TX audio high edge | 1500 Hz – 2950 Hz | 2700 Hz | Transmit audio high edge (SSB). |

#### PTT sequencer

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| PTT line | None / Serial RTS/DTR | None | Where the PTT line for a PA or relays comes from: none, or a USB-serial adapter's RTS/DTR (which drop when the port closes, so a crash leaves the PA unkeyed). *Restarts the radio when saved.* |
| Serial port | text | (empty) | Serial port for the PTT line, e.g. /dev/ttyUSB0. *Restarts the radio when saved.* |
| Line | RTS / DTR / Both | RTS | Which serial line keys the PA. *Restarts the radio when saved.* |
| Sequence delay | 0 ms – 500 ms | 25 ms | Key-up: wait this long after the PTT line before RF; key-down: after RF before releasing it. |

#### Audio

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Noise reduction (NR2) | On / Off | Off | Noise reduction (WDSP's NR2) on what you hear in USB, LSB, CW, AM and FM. Decoders always get the audio without it. |
| Noise reduction strength | 0 % – 100 % | 50 % | How far noise reduction may pull the noise down: 0 % leaves the audio untouched, 100 % up to 40 dB. |

#### Display

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Scope speed | 1 lines/s – 50 lines/s | 20 lines/s | - |
| Wide scope averaging | 1 – 16 | 2 | FFTs averaged per wide line. |
| Zoom scope averaging | 1 – 16 | 2 | - |

#### Local frequencies

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Radius | 1 km – 2000 km | 100 km | Local frequencies lists what is within this distance of the station's locator: airfields, area control, coast stations and marinas, nearest first. |
| openAIP API key | text | (empty) | Your openAIP API key (openaip.net, your profile's API clients), used only when you refresh the local frequencies, to fetch area control around the station. Empty: the copy Radio came with. |

#### Simulator

| Setting | Range or choices | Default | What it does |
| --- | --- | --- | --- |
| Other stations | On / Off | On | Populate the simulated band with other stations. *Restarts the radio when saved.* |
| Time of day (UTC) | real time – 23:59 | real time | Simulate the band at this UTC hour (-1: the real time of day). *Restarts the radio when saved.* |
| Simulated antenna SWR | 1.0:1 – 10.0:1 | 1.3:1 | The simulated antenna's SWR (the SWR guard's test). *Restarts the radio when saved.* |

<!-- settings-ref:end -->

## Keyboard shortcuts

**?** (or the **?** button in the header) shows them all over the window; any key closes it. The single-key shortcuts (arrows, letters, Space) do nothing while you are typing in a box; Esc still unkeys.

![The keyboard shortcuts overlay.](screenshots/shortcuts-1920.png)

| Keys | Does |
| --- | --- |
| **Tuning and bands** | |
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
| B / Shift + B | Next / previous band |
| V | Next register of this band |
| **Transmit** | |
| Space | PTT (hold, or toggle - Settings › Station) |
| Esc | Unkey now, and cancel queued text or a CQ loop (with nothing on the air: close the Controls drawer) |
| T | 1750 Hz toneburst (in FM) |
| Enter | Send the typed line (text modes) |
| F1 … F8 | Send macro 1 … 8 (CW and text modes) |
| F1 … F6 | Send voice memory 1 … 6 (USB, LSB, AM, FM, FreeDV) |
| **Modes and filter** | |
| Ctrl + E | Mode menu: every mode, recent first; type a name (JS8, PSK63, SSTV…) |
| Ctrl + 1 … 5 | USB, LSB, CW, AM, FM |
| Ctrl + 6 … 9 | FT8, FT4, PSK31, RTTY |
| Ctrl + 0 | FreeDV |
| , / . | Filter narrower / wider |
| R | RIT on / off |
| X | XIT on / off |
| S | Split on / off |
| N | Noise blanker |
| Shift + N | Noise reduction |
| M | Mute |
| A | Auto-tune onto the SSB station on the dial |
| Shift + A | Best audio for the station on the dial |
| Right-click on a scope | Auto-tune there (USB, LSB) |
| **Views** | |
| W | Next workspace: Digital, Voice, Watch (kept until you choose a mode) |
| Shift + W | Workspace follows the mode (Auto) |
| Alt + 1 … 9 | Recall memory 1 … 9 |
| Ctrl + J | Operate |
| Ctrl + L | Logbook |
| Ctrl + B | Memories |
| Ctrl + K | CW Activity |
| Ctrl + Shift + D | Decoders |
| Ctrl + Shift + S | Stations (FM and DAB) |
| Ctrl + D | Second display |
| Ctrl + , | Settings |
| Ctrl + Shift + R | Record receive IQ / stop recording |
| Ctrl + Shift + P | Play an IQ recording / back to the radio |
| Ctrl + T | Light / dark theme |
| F11 | Full screen |
| ? | The shortcuts overlay |
| Ctrl + Q | Quit |

JS8, PSK63, PSK125 and SSTV have no Ctrl + number: choose them with Ctrl + E, or on the rail. When you tab to a control, Space works that control instead of the TX button.

## Where things are kept

| What | Where (Linux) | Where (Windows) |
| --- | --- | --- |
| Settings (`config.json`) and window preferences (`ui.json`) | `~/.config/openhamshack-radio/` | `%APPDATA%\openhamshack-radio\` |
| Log (`log.jsonl`), default ADIF export, SSTV pictures | `~/.local/share/openhamshack-radio/` | `%APPDATA%\openhamshack-radio\data\` |
| The program's own log (`openhamshack-radio.log`, see [Sending diagnostics](#sending-diagnostics)) | `~/.local/share/openhamshack-radio/logs/` | `%APPDATA%\openhamshack-radio\data\logs\` |
| IQ recordings (see [Record a sample for the developers](#record-a-sample-for-the-developers)) | `~/.local/share/openhamshack-radio/recordings/` | `%APPDATA%\openhamshack-radio\data\recordings\` |
| Voice memories (see [Voice memories](#voice-memories)) | `~/.local/share/openhamshack-radio/keyer/` | `%APPDATA%\openhamshack-radio\data\keyer\` |

Before 17/10/2026, when the program was OpenHamShack HAM, these folders were called `openhamshack-ham`. The first start of a newer version renames them to `openhamshack-radio` (and, on Linux, leaves a link at each old name), so nothing is copied and nothing is lost.

`OHS_RADIO_CONF`, `OHS_RADIO_DATA` and `OHS_RADIO_UI_CONF` move them. Your own memories, band stacks and power chain are kept in `config.json`. None of it is shared with OpenHamShack QO-100 NB.

From a terminal, `openhamshack-radio --device sim` (or `pluto`, `hl2`, `soapy`) overrides the radio for one run without saving it; `--band 2m`, `--rf 145.5` and `--mode fm` start there for one run; `--no-audio` runs with no sound card; and `openhamshack-radio --headless --seconds 10` runs the receiver alone without a window, printing a status line a second (band, mode, frequency, segment, the licence limit there, processor load and level) - useful for checking a radio from an SSH session. `openhamshack-radio --receive-only` opens the radio as usual but refuses every transmission for that run, whatever the window asks; start without it to transmit again. Headless never transmits. On Windows the same options go to `openhamshack-radio-console.exe` in the program's folder (`%LOCALAPPDATA%\Programs\OpenHamShack Radio`).

## Troubleshooting

**It receives on 70 cm but not on 2 m (or 4 m, or 6 cm).** Your Pluto runs as an AD9363, which tunes 325 MHz–3.8 GHz; 70 cm is inside, 2 m is not. OpenHamShack QO-100 NB works on the same radio because QO-100 is inside too. Use **Help › Check radio…**: if it says *AD9363*, press **Apply the AD9364 setting…** (see [The AD9364 setting](#the-ad9364-setting)), or follow the manual steps it shows. If it already says *AD9364*, use **Help › Save diagnostics…** and send the zip.

**The TX button is greyed.** Hover over it, or over the licence chip: it says why. The usual reasons are the licence tick box, no licence class chosen yet, your licence class (a Foundation licensee on 23 cm, anyone on 60 m but a Full one), a beacon or satellite sub-band, a receive-only radio, and 6 m.

**My licence class is wrong, or says Not chosen.** Settings › Licence & plan › **Licence class**. A new install has none, on purpose: transmit stays locked until you choose. If you used OpenHamShack Radio 0.1.1 or earlier and its Foundation was never confirmed by ticking the licence box, the class was cleared on upgrade for the same reason; Intermediate and Full, and a Foundation you had confirmed, were kept.

**The drive slider will not go up.** The red mark is the band's ceiling (Settings › Bands & power). Your licence's power limit does not hold the slider; it warns, in amber on the Transmit card, when the estimate is over.

**It unkeyed saying the measured power was over my licence.** The radio's forward-power reading was over your class's limit there (Hermes-Lite 2 or simulator, no PA gain entered). Lower Drive to about the figure the notice gives and key again. The Hermes-Lite 2's reading is on a provisional curve until calibrated, so check it against a power meter.

**A band is greyed on the band bar.** Its tooltip says why: the radio cannot tune it (a Pluto running as an AD9363 cannot reach 2 m or 4 m; the Hermes-Lite 2 stops at 38.4 MHz), or it is 6 m.

**Find shows nothing, or "No Pluto found".** Type `ip:192.168.2.1` into **Pluto address** by hand and save: that reaches a Pluto plugged in by USB over its USB network adapter, and needs no USB permissions and no Avahi. If that fails too, check from a terminal: `ping 192.168.2.1` and `iio_info -u ip:192.168.2.1` (from `libiio-utils`). Install `avahi-daemon` for Find to cover everything. For `usb:` addresses, `libiio-utils` must be installed or the udev rule does nothing.

**"This Pluto will not tune … MHz: its firmware runs it as an AD9363".** Your Pluto is limited to 325 MHz - 3.8 GHz: see the first entry above.

**"No Hermes-Lite 2 answered … on UDP port 1024".** Is it powered, and has it had about 15 seconds to get an address (without DHCP it falls back to 169.254.19.221)? Is a firewall dropping UDP ports 1024 and 1025? A radio on another subnet needs its address in **Hermes-Lite 2 address**. "Already streaming to another program" means another program has it open.

**"The PTT sequencer's output could not be opened".** The serial port named in Settings › PTT sequencer does not exist or you may not open it. On Debian and Ubuntu, add yourself to the `dialout` group (`sudo adduser $USER dialout`, then log out and in). Transmit is refused until it is fixed.

**Transmit stops after three seconds.** That is dead air: no sound from the microphone. Settings › Audio, **Listen to the microphone**, and speak: the meter should move.

**"Unkeyed: SWR … is above the … limit".** Check the antenna and feeder, then press **SWR tripped: acknowledge** on the Transmit card.

**No sound.** Settings › Audio: is the right **Speaker** chosen, and does **Play a test tone** play? Then check **Volume** and **Mute** (M), and in FM the **Squelch**.

**FT8 or FT4 is greyed.** The program's own decoder (ohsdigi) is missing or damaged: reinstall OpenHamShack Radio. With the `all` package, which has no ohsdigi, install WSJT-X instead: `sudo apt install wsjtx`. **FT8 shows no decodes**: check the dial (the FT8 button on the band bar), and the computer's clock.

**Overruns climb in the status strip.** The computer is not keeping up. Use a lower sample rate (1.2 MS/s on a Pluto, 192 kS/s on a Hermes-Lite 2), reduce **Scope speed** in Settings › Display, close other programs.

**It will not start at all.** Run `openhamshack-radio` from a terminal (on Windows, **OpenHamShack Radio (console)** from the Start menu) and read what it says. "The window needs PyQt6" means `python3-pyqt6` is missing. Either way, the end of the program's own log (below) usually says why.

## Diagnostics

### Check radio

**Help › Check radio…** asks the Pluto what it is and lists the answers: whether it answers at all, its model, serial and firmware, which chip it runs as, the sample rate and FIR, and for each VHF/UHF band your licence includes, whether this radio can tune it. When the radio will not start, the message that says so has **Check radio…** and **Save diagnostics…** buttons.

![Check radio on a stock Pluto: 70 cm in range, 2 m, 4 m and 6 cm needing the AD9364 setting](screenshots/diag-check-radio.png)

### The AD9364 setting

A Pluto as it comes from ADI tells its driver it is an AD9363, which limits it to 325 MHz–3.8 GHz. The hardware covers 70 MHz–6 GHz, and ADI documents how to tell the driver it is an AD9364 instead. OpenHamShack QO-100 NB never needs this. OpenHamShack Radio needs it for 2 m, 4 m and 6 cm.

When you pick one of those bands on a Pluto that runs as an AD9363, or OpenHamShack Radio starts on one, it says so:

![This Pluto is running as an AD9363, which tunes 325 MHz–3.8 GHz. 2 m needs the AD9364 setting.](screenshots/diag-chip-mode.png)

**Apply the AD9364 setting…** first shows you the exact commands it will run on the radio and what each does, and runs nothing until you press **Run these commands**. It then logs in to the Pluto over its network link (SSH, as root, with ADI's default password `analog`; if you changed it, you are asked once, and the password is used for that connection only and never saved), changes the setting, restarts the radio, waits for it to come back - about half a minute - and checks that it now runs as an AD9364. Receiving stops while it does this and starts again afterwards. **Help › Check radio…** offers **Undo (back to AD9363)** on a Pluto that runs as an AD9364, which restores ADI's default the same way.

It changes two settings the radio reads when it starts, not the firmware. It uses ADI's own commands, which differ by firmware version: v0.32 and later, `fw_setenv compatible ad9364`; before v0.32, `fw_setenv attr_name compatible` and `fw_setenv attr_val ad9364`; then `reboot`. It only runs them on ADI firmware it knows (v0.26 to v0.39). On anything else - Tezuka, a newer ADI release, a clone's own firmware - and on a Pluto reached only as `usb:` (the change needs the Pluto's network link, `ip:192.168.2.1`), it shows you the steps to do it by hand instead:

1. `ssh root@192.168.2.1` (password `analog`). Windows 10 and 11 have `ssh` built in; PuTTY works too.
2. The commands above for your firmware version (Check radio… shows it).
3. `reboot`, wait half a minute, then **Radio › Restart the radio** and **Help › Check radio…** to confirm.

## Sending diagnostics

When something goes wrong, or looks odd, **Help › Save diagnostics…** makes one zip file to email to Brian. It holds:

- the program's log of this run and the ones before it;
- your settings (`config.json` and `ui.json`) - your callsign and locator are left in, anything that looks like a password is removed;
- `report.txt`: the program and system versions, which libiio, WSJT-X, FT8/FT4 encoder, codec2 and sound devices it found, the radio's firmware, model and serial, the band, licence class and transmit state, and your screen's size and scaling;
- a picture of the main window (only the window, not the rest of your screen);
- the last two minutes of status, a line a second.

OpenHamShack Radio adds what it finds itself, in `report.txt`'s last section: what **Find** sees now, and for a Pluto what it says it is - reachable or why not, firmware, which chip it runs as, its tuning range, and whether the AD9364 setting can be changed for you. It asks the radio afresh when it would not open, which is when the report matters most, so collecting takes a few seconds before the dialog appears.

The dialog lists every file before anything is saved. **Save…** asks where (the Desktop on Windows, your home folder on Linux); **Open folder** then shows the zip, ready to attach. Nothing is sent by the program itself.

The log is always on: `openhamshack-radio.log` in `~/.local/share/openhamshack-radio/logs/` on Linux and `%APPDATA%\openhamshack-radio\data\logs\` on Windows (**Help › Open log folder** goes there). It keeps about 10 MB - five old files beside the current one - and records start-up, the radio opening and closing, band changes, the PTT sequencer and SWR trips, overruns, which settings changed (not what you set them to) and any error. For more detail, start it with `-v`: `openhamshack-radio -v` on Linux, or `openhamshack-radio-console.exe -v` on Windows, which also shows the log live in its console window.

## Record a sample for the developers

When you hear or see something odd - a signal that will not decode, a spur, interference, a band that looks wrong - a recording lets Brian look at exactly what your radio received, at his desk, as often as he likes. It records the radio's whole receive signal (everything the wide scope shows, not just the audio), with a note of how your station was set up.

1. Tune to where the odd thing is, in the mode you were using.
2. **File › Record receive IQ…** (Ctrl + Shift + R). The window says how much disk it takes before anything is written - at 1.2 MS/s about **4.8 MB a second, 290 MB a minute** (a Hermes-Lite 2 at 192 kS/s, about 46 MB a minute) - and how much room there is. A minute or two is usually plenty; set **Stop by itself after** if you would rather not watch the clock (it is remembered).
3. **Record**. While it records, the status strip at the bottom shows a red **● REC** with the time and size so far. Carry on operating as normal; what you transmit is never recorded, and the recording notes when you transmitted.
4. **File › Stop recording** (Ctrl + Shift + R again) stops it. A message says the recording is saved, with its name.

**File › Open recordings folder** opens the folder: `%APPDATA%\openhamshack-radio\data\recordings\` on Windows, `~/.local/share/openhamshack-radio/recordings/` on Linux. Each recording is **two files with the same name**, for example `openhamshack-radio-20261007-182100Z-144.300MHz-USB.sigmf-data` and `….sigmf-meta`. **Send both**: the `.sigmf-data` file is the signal, the `.sigmf-meta` file says what it is (frequency, sample rate, when, band and any converter, gain, radio and firmware, the program and system version, your callsign) - one without the other is no use. The data file is too large for email; a file-sharing link (OneDrive, Google Drive, WeTransfer) is the way to send it. A note of what you noticed, and roughly when in the recording, helps.

Recording takes almost no processing, so it does not disturb receive. If the disk cannot keep up, the program drops pieces rather than holding up the radio; the message at the end says so, and the files record where the gaps are. Stopping the radio, a Settings change that restarts it, or closing the program also ends a recording, and saves it properly.

The files are in SigMF, an open format: any SigMF tool (inspectrum, GNU Radio, the `sigmf` Python package) can open them too.

## Play a recording

**File › Play IQ recording…** (Ctrl + Shift + P) plays a recording - yours, or one somebody sent you - through the receiver in place of the radio: the scopes, the decoders and the speaker all work on it exactly as on the air, and FT8 decodes carry the time they were sent. Choose either file of the pair; both must be in the same folder. The recording's band, frequency and mode come with it.

While it plays, the status strip shows **▶ PLAYBACK** with the recording's name, how far in it is, and when that moment was recorded. Nothing can be transmitted (the TX button says why) and nothing new can be recorded. You can tune anywhere the recording covers; another band is refused. **File › Loop playback** starts it again from the beginning when it ends; without it, the end is silence and a message.

**File › Back to the radio** (Ctrl + Shift + P again) returns to your radio, on the frequency and mode you had before.

## Not yet verified

OpenHamShack Radio 0.1.0 has been built and tested against its own simulator. Be clear about what that does and does not show.

- **Auto-tune and best audio** were tried only on QO-100 voices, through OpenHamShack QO-100 NB, which shares their code: receive only, with a weak dish. Auto-tune answered on about a third of its tries and refused the rest. Its answers agreed to within a few hertz, and it refused beacons and data signals. On HF, nothing has been tried: fading, splatter and crowded bands.
- **Nothing has been on air, and no real radio has been connected.** It has not run against a real ADALM-Pluto, Pluto+, LibreSDR, Pluto nano, Hermes-Lite 2 or SoapySDR receiver, nor on a Raspberry Pi.
- **The control pad** has never been used with a real AKP03E in this program: everything is tested against a simulated pad built from reports captured on a real one under Linux. On Windows and macOS which part of the pad is opened, and how its pictures are sent, follow other open-source drivers and hidapi's own code; the first real pad on Windows is the test. If it does nothing, **Settings › Control pad › Copy controller report** says what was seen.
- **Pluto receive and transmit on 2 m and 70 cm are unproven.** The Pluto driver is OpenHamShack QO-100 NB's, itself proven only against a simulator; the terrestrial bands, the AD9363/AD9364 check, 4 m on the receiver's floor, the transmit LO placement and its leakage, and the Pluto's real output power at these frequencies are all untested.
- **The Hermes-Lite 2 has only met an emulator** written from the same documents as the driver, so the two agree by construction and would share any misreading. Unsettled until a real radio: the transmit I/Q order, the forward and reflected power calibration (provisional), the TX-inhibit polarity, the filter-board bits above 30 MHz, and the drive steps.
- **Power figures are estimates.** The power warning works from the power chain you enter; the Pluto's 4.5 mW and the Hermes-Lite 2's 5 W are published figures, not measurements of your radio. The measured-power limit has been tried only against the simulator and the Hermes-Lite 2 emulator, and the Hermes-Lite 2's forward-power calibration is provisional.
- **The S-meter's calibration** is tested against the simulator only. Whether a radio's gain steps really move its readings one-for-one (which is what lets a calibration survive a gain change) is unmeasured; calibrate at the gain you use until it has been checked.
- **The PTT sequencer's serial driver** has been tested against a recording fake, not a real USB-serial adapter and relay; its timing has not been measured on a scope.
- **Updating itself** has been tested against a signed test feed on this computer only. The first real update will be from the first release that carries it to the one after; the Windows installer's unattended run and restart have not yet been tried on Windows.
- **The licence and band-plan data** were checked against Ofcom's and the RSGB's PDFs on 4 October 2026. Both change; check them against the current documents yourself.
- **Noise reduction** has been measured on the simulator's synthetic speech in synthetic noise, not heard on a real signal. Whether 50 % is the right default, and how it sounds on real SSB and CW, is for the ear to judge on air; its cost on a Raspberry Pi is an estimate.
- **FT8 and FT4 sending** uses OpenHamShack Radio's own encoder. It gives the same symbols as WSJT-X 2.7.0's for every message it was compared on (over 150,000, every message type), and WSJT-X's `jt9` decodes what it sends, on Linux and on Windows; but nothing has been sent on air with it yet. The Raspberry Pi (`arm64`) package's encoder has been built but never run on a Pi.
- **On Windows** the program has been installed and run on the simulator on a Windows 11 virtual machine, and nothing more: no radio or sound card has been tried with it there. FT8 has decoded the simulator's signals there through the bundled WSJT-X tools, with no WSJT-X installed. The installer's PlutoSDR USB drivers option has been tried there only without a desktop session, so Windows' *install this device software?* question has not been seen through it.

When you do try it on a radio: **receive first**. Then transmit into a dummy load with a spectrum analyser on it - the harmonics, the leakage carrier, which sideband came out - then through the PA into a dummy load with a power meter, entering what you measure in Settings › Bands & power. Only then an antenna, at low drive.

## Known problems

None listed for this release. What has not been checked on real hardware is under [Not yet verified](#not-yet-verified) - read that before transmitting.
