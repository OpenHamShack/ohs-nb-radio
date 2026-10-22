# Hermes-Lite 2: research notes for OpenHamShack HAM

Compiled 2026-10-04 for `DESIGN-HAM.md` §4.2. Nearly every fact comes from
a primary source: the HL2 wiki, the gateware Verilog at current `master`
(which reports version 74.2; the newest stable bitfile is `20231230_74p2`),
the TAPR Metis and USB protocol documents, the HL2 project's own
`hermeslite.py`, Quisk 4.2.54 and N2ADR's pages. Each fact carries a
source key from the list at the end.

Markers, as in `docs/qo100-research.md`:

- **[unverified]**: could not be confirmed from a primary source.
- **[derived]**: worked out from cited facts, not stated anywhere.
- **[GW file]**: read in the gateware source; the file is named.

Nothing here has been checked on Brian's HL2 yet.

## What the design must know first

1. **No 6 m.** The HL2 covers 0–38.4 MHz [FAQ].
2. **No SWR protection.** The gateware has no ALC and no SWR or
   reflected-power fold-back; reverse power is telemetry only
   [GW control.v, derived from a search of the source]. The application must
   protect the PA.
3. **TX stops by itself.** It ends ~12 ms after the host stops sending TX
   samples, and a watchdog stops all streaming if host packets stop
   [GW radio.v, dsopenhpsdr1.v].
4. **A thermal cut-out exists**, at ~55 °C off and ~50 °C back on. Enabling
   "band volts" bypasses it [GW control.v].
5. **openHPSDR Protocol 1 only**, plus HL2 extensions. There is no Protocol 2
   [SW][GW].
6. **No iambic keyer in the standard gateware.** It supports a straight key,
   an external keyer, and host-keyed CWX [GW].
7. **Drive has only 16 steps over 7.5 dB.** Lower levels come from scaling
   the IQ amplitude [P][SW].
8. **Licences.** Quisk, piHPSDR, linHPSDR and the gateware are GPL.
   `hermeslite.py` has no licence. Implement from the documents; do not copy
   client code (DESIGN-HAM question 11).

---

## 1. Hardware

| Item | Value | Source |
|---|---|---|
| Codec | AD9866, 12-bit ADC and DAC. ADC clock **76.8 MHz**, DAC 153.6 MHz | [FAQ] |
| FPGA | Cyclone IV EP4CE22 | [GW] |
| RX coverage | **0–38.4 MHz**, possibly attenuated 30–38.4 MHz. Below 130 kHz may need hardware or software changes. "No 6 m, unlike the Hermes." | [FAQ] |
| TX power | about **5 W on all HF amateur bands** | [FAQ] |
| Low-pass filters (N2ADR board) | 160–10 m | [N2F] |
| Low-power output RF1 | ≤ 17 dBm, used when the PA is disabled (e.g. for a transverter) | [EXT][SW] |
| TX hardware gain | 0 to 7.5 dB in the AD9866. It cannot reach zero: "37 dBm becomes 29.5 dBm" at full cut. Lower levels need IQ scaling. | [SW] |
| Supply | 11–16 V DC, ≥ 2 A, 12–13.8 V preferred; 2.1 mm centre-positive barrel, reverse-polarity protected | [EXT] |
| PA bias | 180–220 mA keyed, set at the factory. TX test points: Vpa 8.0 V, Vop 10.15 V, Vbias 10.0 V | [NOTX] |
| Bias setting | I2C bus 2: `0x06ac00vv` volatile bias0, `0x06ac20vv` non-volatile bias0, `0x06ac10vv` / `0x06ac30vv` bias1. 0xFF is the lowest bias. **OpenHamShack HAM never writes these.** | [P] |
| Network | 100 Mb/s or 1 Gb/s, auto-sensed. Avoid Wi-Fi. | [EXT][NET][FAQ] |

### Telemetry

The ADS7828 slow ADC delivers four 12-bit values: temperature, forward
power, reverse power and bias current [P][GW control.v].

| Quantity | Conversion | Source |
|---|---|---|
| Temperature (°C) | (3.26·raw/4096 − 0.5) / 0.01 | [HLPY][QW] |
| Bias current (A) | ((3.26·raw/4096)/50)/0.04, divided by 1000/1270 for an input divider | Quisk [QW] |
| Forward / reverse power | **a calibration table, not a formula** | Quisk [QC] |
| SWR | Γ = √(rev/fwd), SWR = (1+Γ)/(1−Γ), only when fwd ≥ 0.05 W | Quisk [QW] |

- **Bias current.** `hermeslite.py` omits the divider, so the two sources
  disagree **[unverified which is right]**. Quisk shows the value in its UI,
  so it is the likelier.
- **Power table.** Quisk's `HL2FilterE3` is a spline from raw ADC to watts,
  for example 3382 → 4.98 W and 4093 → 7.29 W. OpenHamShack HAM builds its own
  table against a power meter.
- **Polarity.** Quisk swaps forward and reverse when reverse reads higher,
  because the sense transformer's polarity varies between units.

## 2. Protocol 1 framing

### Discovery

- **Request:** `EF FE 02` plus 60 zero bytes to UDP port **1024**, broadcast
  (the Metis spec uses 255.255.255.255) [METIS].
- **Port 1025:** the HL2 also listens here, which `hermeslite.py` uses so it
  can run alongside SDR software [HLPY][NET].

The reply is 60 bytes [P][HLPY]:

| Bytes | Content |
|---|---|
| 0x00–0x01 | `EF FE` |
| 0x02 | 0x02 idle, 0x03 sending |
| 0x03–0x08 | MAC address |
| 0x09 | gateware major version |
| 0x0A | board ID: **0x06 = HL2**, 0x01 = Hermes emulation |
| 0x0B | EEPROM config: bit 7 valid IP, bit 6 valid MAC, bit 5 favour DHCP |
| 0x0D–0x10 | fixed IP |
| 0x11–0x12 | alternate MAC bytes |
| 0x13 | number of hardware receivers |
| 0x14 | bits 7:6 wideband format (00 = 12-bit, 01 = 16-bit); bits 5:0 build board ID |
| 0x15 | gateware minor version |
| 0x17–0x1A | response data |
| 0x1B | bit 7 external CW key, bit 6 PTT, bits 1:0 clip count; `hermeslite.py` also reads bit 5 pa_exttr, bit 4 pa_inttr, bit 3 tx_on, bit 2 cw_on |
| 0x1C–0x23 | temperature, forward, reverse and bias current, 12-bit each |
| 0x24 | TX FIFO recovery flag and count MSBs |

### Start and stop

`EF FE 04 <cmd>` plus 60 zero bytes [METIS].

- Bit 0 starts IQ streaming.
- Bit 1 starts wideband data.
- **HL2 bit 7 disables the watchdog** [P]. OpenHamShack HAM never sets it.
- Sequence numbers reset on stop. The host resets its own to 0 at each start
  [METIS].

### Data packets

- **Packet:** 1032 bytes, `EF FE 01 <endpoint> <seq32 big-endian>` followed
  by two 512-byte frames. Each endpoint keeps its own sequence [METIS].
- **Frame:** `7F 7F 7F C0 C1 C2 C3 C4` followed by samples [USB].
- **EP6 (radio to host):**
  - Per sample, for each receiver: 24-bit I then 24-bit Q (big-endian,
    two's complement), then one 16-bit mic word [USB].
  - Samples per frame = ⌊504/(6N+2)⌋: 63 for one receiver, 36 for two, 19
    for four [derived; padding is tabled in USB].
  - The HL2 has no audio codec, so the mic words carry nothing useful
    **[unverified content]**.
- **EP2 (host to radio):**
  - 63 samples per frame, each L1 L0 R1 R0 I1 I0 Q1 Q0, all 16-bit,
    **always 48 kHz** [USB].
  - The HL2 ignores the L/R audio. It reuses the first sample's L/R bytes as
    a 16-bit extended address (EADDR) [P].
- **TX I/Q order.** The USB spec says TX I/Q is swapped relative to RX, "a
  historical bug" [USB]. Whether HL2 clients swap is **[unverified]**. The
  `hl2sim` test cannot settle it; the first on-air check against a known
  tone offset must.
- **Wideband data:** endpoint 0x04, 512 16-bit samples per packet. A
  2048-sample block spans four packets and starts when `seq & 3 == 0` [P].
  Not used by the design.

## 3. Sample rates, receivers, bandwidth

- **RX rates:** 48, 96, 192 or 384 kHz, from register 0x00 bits 25:24, and
  changeable live. Each is 76.8 MHz / (5·{40, 20, 10, 5}·8) [P][ARCH].
- **TX and mic rate:** fixed at 48 kHz [USB].
- **Receivers:**
  - The standard build has 4 (`hl2b5up_main`, NR=4) [SW][GW hermeslite.v].
  - RX-only skimmer builds have 9 [FAQ].
  - The register map allows up to 12 [P].
  - Register 0x00 bits 6:3 hold receivers − 1 [P].
- **Load [derived]:**

  | Configuration | Packets/s | Data rate |
  |---|---|---|
  | 1 RX at 384 kHz | ~3 048 | ~26 Mb/s |
  | 1 RX at 192 kHz | ~1 524 | ~13 Mb/s |
  | 4 RX at 384 kHz | ~10 100 | ~87 Mb/s (gigabit) |
  | EP2 (host to radio) | 48 000/126 ≈ 381 | — |

  The packet rate, not the data rate, is what costs Python time, which is
  why DESIGN-HAM sets 192 kHz as the default.

## 4. Command and control (C&C) registers

**C0 layout:**
- bit 7 = RQST, an HL2 extension that asks for an acknowledged write
- bits 6:1 = register address
- bit 0 = **MOX**

C1–C4 carry DATA[31:0], C1 most significant. In openHPSDR terms
"C0 = 0x12" is therefore address 0x09 [P][USB].

| Address | Bits | Meaning |
|---|---|---|
| 0x00 | 25:24 | sample rate |
| 0x00 | 23:17 | **open-collector OC0–6**, sent to the filter board |
| 0x00 | 13 | RX antenna, sent as I2C bit 7 |
| 0x00 | 12 | power-supply switching clock off |
| 0x00 | 11 | fan PWM (0) or band volts (1). **Band volts bypasses thermal protection (§7).** |
| 0x00 | 6:3 | number of receivers − 1 |
| 0x00 | 2 | duplex |
| 0x01 | — | TX NCO frequency, Hz |
| 0x02–0x08 | — | RX1–RX7 frequency (RX8–12 at 0x12–0x16) |
| 0x09 | 31:24 | drive level; **only bits 31:28 used**, 16 steps over 7.5 dB [P][GW ad9866ctrl.v] |
| 0x09 | 23 | VNA |
| 0x09 | 20 | tune request |
| 0x09 | **19** | **PA enable** |
| 0x09 | 18 | disable T/R relay when the PA is off |
| 0x09 | 17 | ATU bypass |
| 0x09 | 15:8 / 7:0 | Alex RX / TX filter |
| 0x0A | 6 | 1 = LNA[5:0] is direct gain, 0..60 → **−12..+48 dB** |
| 0x0A | 5 | step attenuator enable (legacy Hermes mode) |
| 0x0A | 22 | PureSignal |
| 0x0E | 15 / 14 / 13:8 | hardware-managed TX LNA enable / direct encoding / TX LNA gain [GW ad9866.v] |
| 0x0F | 24 | **CWX enable** |
| 0x10 | 31:24 + 17:16 | CW hang time, 10 bits, ms |
| 0x17 | 12:8 | **PTT hang**, default 12 ms; 31 = hang until MOX drops [GW radio.v] |
| 0x17 | 6:0 | **TX buffer latency**, default 20 ms |
| 0x39 | 27:24 | 0x8 enable / 0x9 disable watchdog. Also NCO sync and clock commands. |
| 0x3A | 0 | reset on disconnect |
| 0x3B | — | AD9866 SPI (cookie 0x06) |
| 0x3C / 0x3D | — | I2C bus 1 / bus 2: cookie 0x06 write, 0x07 read; then address, register, data |
| 0x3F | — | error response |

Every address is from [P] unless another source is named.

**How Quisk encodes these [QH]:**
- RX LNA byte = ((dB+12) & 0x3F) | 0x40, sent in C4 of address 0x0A.
- TX LNA = the same value | 0x80, sent in C3 of address 0x0E.
- TX level goes in C1 of address 0x09.

### Responses (radio to host) [P][GW control.v]

**ACK = 0.** C0 bits 6:3 = RADDR, bit 2 = dot (key tip), bit 0 = PTT. The
registers rotate:

| Address | Content |
|---|---|
| 0 | bit 25 TX inhibit (active low); bit 24 ADC overload; bits 15:14 FIFO underflow (10) or overflow (11); bits 14:8 TX FIFO count MSBs; bits 7:0 firmware version |
| 1 | temperature in bits 31:16 (12-bit value); forward power in bits 15:0 |
| 2 | reverse power in bits 31:16; current in bits 15:0 |

**ACK = 1.** Echoes the requested address and data, or I2C read data.

- Keep at most one RQST outstanding.
- Set RQST on at most about every other frame [P].

**EEPROM:** MCP4662 on I2C 0x3D, device 0xAC. It holds the fixed IP, the
MAC and the DHCP preference [P].

## 5. Filter board, I/O board, PA keying

### N2ADR filter board

- **How it is driven:** the gateware writes OC bits 6:0, with the RX antenna
  bit as bit 7, to I2C address 0x20 (an MCP23008) [P].
- **RX and TX use the same bits**, unless "Alex manual mode" is set, which
  is not implemented [P].

**Bit map [N2F][SW]:**

| Bit | Function |
|---|---|
| 0 | 160 m LPF |
| 1 | 80 m LPF |
| 2 | 60/40 m LPF |
| 3 | 30/20 m LPF |
| 4 | 17/15 m LPF |
| 5 | 12/10 m LPF |
| 6 | **3 MHz HPF**, RX only (blocks AM broadcast) |
| 7 | free, on a pad (antenna select) [P] |

**Quisk's default band map [QC]:**

| Band | Bits |
|---|---|
| 160 m | 0x01 |
| 80 m | 0x42 |
| 60/40 m | 0x44 |
| 30/20 m | 0x48 |
| 17/15 m | 0x50 |
| 12/10 m | 0x60 |

- The HPF is in from 80 m up.
- With several receivers, Quisk selects for the highest band among them [QH].
- **160 m tip:** leave the filters out on RX at 160 m. The PSU's ~900 kHz
  second harmonic couples into them [OPT].

### PA keying and rear connectors

- **EXTTR** (rear phono jack) [EXT]:
  - Open-collector, pulled low during TX.
  - Pull-up to 28 V maximum, 1 W maximum (150 Ω minimum at 12 V).
  - Follows the internal TX state whether or not the PA is enabled
    [GW control.v].
  - **This is the HL2's own PA/sequencer PTT output.**
- **ACC2** can carry HR50 band data over UART [EXT].
- **ACC1** drives an AH-4 ATU [EXT].
- **Band volts** (gateware 72p5 and later): the fan PWM output is reused as
  230–2300 mV per band, for amplifiers that select their band from a
  voltage [BV]. It defeats thermal protection (§7).

### N2ADR I/O board [IOB]

- **Hardware:** a Pico microcontroller at I2C 0x1D on bus 2. Its hardware ID,
  at 0x41 register 0, reads 0xF1.
- **Resources:**
  - 8 outputs, at 5 V or as low-side switches (50 V / 500 mA)
  - 5 protected inputs
  - a UART
  - an RX SMA input and a PureSignal SMA input
  - a fan driver
  - EXTTR sense
- **Registers:**
  - 0–4: TX frequency (40-bit, big-endian)
  - 5: control
  - 7: ATU
  - 8: fault
  - 11: RF inputs
  - 12: fan
  - 13–24: RX frequency codes
  - 31: antenna
- Reads return 4 bytes.
- MIT licence.

## 6. CW

- **Key/PTT jack:** 3.5 mm, tip = key, ring = PTT [EXT].
- **No iambic keyer in the standard gateware:**
  - The main build is compiled with CW=1 ("CW_BASIC"), which supports a
    straight key or an external keyer [GW hl2b5up_main/hermeslite.v, control.v].
  - The iambic keyer (registers 0x0B speed/mode/weight, 0x0F PTT delay,
    0x11) exists only in CW=2 builds [GW cw_openhpsdr.v].
  - The wiki's Architecture page says a keyer is present. That page is
    AI-generated and wrong on this point [ARCH vs GW].
- **Jack keying** [P][EXT]:
  - Grounding the tip produces gateware-shaped CW, with PTT held through the
    CW hang time.
  - **Host MOX must be 0 while sending CW this way.**
  - From gateware 71p2, the ring can act as a foot switch together with the
    tip.
- **CWX** (address 0x0F bit 24) [P][GW dsopenhpsdr1.v]:
  - The host keys the gateware's CW generator through the EP2 TX I sample:
    bit 0 = key down, bit 3 = key up.
  - It works while MOX = 0.
  - TX is held for 500 ms of spacing after the last element.
- **Timing [GW radio.v]:**
  - Key-down is delayed by the TX buffer latency, so RF lines up with the
    audio path.
  - Linear rise and fall shaping.
  - The CW hang register (0x10) sets break-in.

## 7. Safety-relevant behaviour

- **What happens when the host goes quiet:**
  - TX samples enter the FIFO only while MOX = 1, and each sample carries a
    PTT flag [GW dsopenhpsdr1.v].
  - When samples stop, TX ends after the PTT hang (default 12 ms), unless
    PTT hang is 31 [GW radio.v][NET].
  - **Old gateware stayed in TX** [NET]. OpenHamShack HAM sets a minimum gateware
    version.
- **Watchdog:**
  - It counts while running without received EP2 packets, then forces run,
    wideband and PTT off [GW dsopenhpsdr1.v][P].
  - Its timeout comes from the wideband timer. "About 4 s" appears only on
    the AI-generated page **[unverified]**.
  - Disable it only for RX-only use [P][QC].
- **TX gating** [GW control.v]:

  ```
  int_tx_on = (tx_on | ext_ptt) & ~tx_inhibit & run & temp_enabletx
  ```

  A hardware TX-inhibit input on CN8 [IO] is reported in response address 0,
  bit 25 [P].
- **Thermal cut-out** [GW control.v]:
  - The fan state machine enters OVERHEAT above ~55 °C, which blocks TX,
    and re-enables below ~50 °C, with 2-sample voting.
  - **With band volts enabled the thermal logic is bypassed.** This is our
    reading of the source; to be confirmed on the hardware or with the
    author.
- **SWR:** there is no reflected-power fold-back anywhere in the gateware
  [derived from a source search, GW control.v].
- **PA disable:** address 0x09 bit 19 = 0 routes output to RF1; bit 18
  disables the T/R relay [P][GW control.v].
- **Drive practice** [NOTX][USB]:
  - Drive is set by the drive register; IQ peaks at ±1.0.
  - Running at the maximum 7.5 dB hardware gain is normal.
  - Some client software refuses to transmit without a 48 kHz audio device.
    This is a client quirk, not an HL2 requirement.

## 8. Network, latency, pitfalls

- **Addressing** [NET][GW-UP]:
  - DHCP by default. Without a DHCP server the HL2 falls back to APIPA after
    15 s, trying **169.254.19.221** first.
  - A fixed IP and MAC can be stored in EEPROM.
  - Grounding tip and ring at power-on ignores the EEPROM settings and boots
    the factory image.
- **Firewall:** open ports 1024 and 1025 [NET]. Windows Firewall is the
  usual cause of "no radio found".
- **IP stack:** a single-entry MAC/IP cache, so the HL2 replies to whoever
  spoke last [ARCH]. Two clients on one HL2 do not work.
- **TX buffer** [NET][ARCH][P]:
  - The FIFO holds about 16k samples, roughly 70–80 ms.
  - Defaults are 20 ms latency and 12 ms PTT hang (gateware 72p8 and later).
    Quisk uses 10 ms and 4 ms [QC].
  - An underrun gives a silent gap and **relay chatter**. Under- and
    overflow are flagged in response address 0, bits 15:14.
- **Gateware update** [METIS][HLPY][GW-UP]:
  - `EF FE 03 02` erases; `EF FE 03 01 <blocks> <256 bytes>` programs;
    replies are 0x03 or 0x04.
  - The image is an `.rbf` written to slot 2; the factory image stays in
    slot 1 as a fallback.
  - OpenHamShack HAM does not update gateware (DESIGN-HAM §10).

## 9. Implementations and licences

- **Protocol:** the HL2 works with "all software supporting openHPSDR
  protocol 1" [SW][P]. The gateware contains only Protocol 1 parser and
  packer modules [GW].
- **`hermeslite.py`** (HL2 repo, `software/hermeslite/`) [HLPY]:
  - The official reference for discovery, configuration over port 1025,
    EEPROM, gateware update and the I/O board.
  - **No licence header, and no LICENSE file in the repo.** The gateware
    itself is GPL-2+.
- **Quisk** (Python + C, GPL) [QPYPI][QH]:
  - `hermes/quisk_hardware.py` is the most complete HL2 control reference.
  - Copying from it would make OpenHamShack HAM GPL.
- **piHPSDR (DL1YCF fork) and linHPSDR (M5EVT fork):** GPL **[unverified
  licence text]**.
- **SparkSDR:** free but closed source [SW].

---

## Sources

- [P] Protocol: https://github.com/softerhardware/Hermes-Lite2/wiki/Protocol
- [FAQ] https://github.com/softerhardware/Hermes-Lite2/wiki/FAQ
- [EXT] https://github.com/softerhardware/Hermes-Lite2/wiki/External-Connections
- [IO] https://github.com/softerhardware/Hermes-Lite2/wiki/IO
- [SW] https://github.com/softerhardware/Hermes-Lite2/wiki/Software
- [NET] https://github.com/softerhardware/Hermes-Lite2/wiki/Troubleshoot-Network
- [GW-UP] https://github.com/softerhardware/Hermes-Lite2/wiki/Updating-Gateware
- [NOTX] https://github.com/softerhardware/Hermes-Lite2/wiki/No-Transmit
- [OPT] https://github.com/softerhardware/Hermes-Lite2/wiki/Options
- [BV] https://github.com/softerhardware/Hermes-Lite2/wiki/Band-Volts
- [ARCH] https://github.com/softerhardware/Hermes-Lite2/wiki/Architecture.
  The wiki flags this page as AI-generated. Used only where nothing better
  exists, and marked where it is wrong.
- [GW] https://github.com/softerhardware/Hermes-Lite2/tree/master/gateware/rtl.
  The file is named at each citation.
- [HLPY] https://github.com/softerhardware/Hermes-Lite2/blob/master/software/hermeslite/hermeslite.py
- [METIS] https://github.com/TAPR/OpenHPSDR-Firmware/blob/master/Protocol%201/Documentation/Metis-%20How%20it%20works_V1.33.pdf
- [USB] https://github.com/TAPR/OpenHPSDR-SVN/blob/master/Documentation/USB_protocol_V1.58.doc
- [QPYPI] https://pypi.org/project/quisk/ (4.2.54):
  - [QH] `quisk/hermes/quisk_hardware.py`
  - [QW] `quisk/hermes/quisk_widgets.py`
  - [QC] `quisk/quisk_conf_defaults.py`
- [N2F] http://james.ahlstrom.name/hl2filter/
- [IOB] https://github.com/jimahlstrom/HL2IOBoard (README, `i2c_registers.h`)
