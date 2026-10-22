# QO-100 NB transceiver appliance: research notes

Compiled 2026-10-04. Every number has a source. Anything I measured on this host is marked **[local]**. Anything I worked out myself rather than found stated is marked **[derived]**. Anything I could not confirm is marked **[unverified]**.

---

## 1. Transponder, bandplan, conversion, polarisation

| Item | Value | Source |
|---|---|---|
| Orbit | Geostationary, 26° E; launched 15 Nov 2018 | Wikipedia (Es'hail 2) |
| NB uplink | 2400.000–2400.500 MHz, **RHCP** | AMSAT-DL bandplan; Wikipedia |
| NB downlink | 10489.500–10490.000 MHz, **vertical linear** | AMSAT-DL bandplan |
| Transponder LO (conversion) | **8089.500 MHz**, non-inverting (downlink = uplink + 8089.5 MHz) | Wikipedia; RadCom/OARC Easy-100; SDR Console defaults (TX converter 8089.5) |
| Width | ~500 kHz, widened from ~250 kHz on **23 Dec 2020** | AMSAT-DL "New QO-100 band plan" |

### Bandplan (AMSAT-DL, current page)

| Uplink MHz | Downlink MHz | Width | Use |
|---|---|---|---|
| – | 10489.500–10489.505 | 5 kHz | **Lower beacon** 10489.500, CW F1A with 400 Hz shift, plus guard |
| 2400.005–2400.040 | 10489.505–10489.540 | 35 kHz | CW only |
| 2400.040–2400.080 | 10489.540–10489.580 | 40 kHz | Digimodes, **500 Hz max BW** |
| 2400.080–2400.150 | 10489.580–10489.650 | 70 kHz | Digimodes, **2700 Hz max BW** |
| 2400.150–2400.245 | 10489.650–10489.745 | 95 kHz | SSB only (2.7 kHz) |
| – | 10489.745–10489.755 | 10 kHz | **Middle beacon** 10489.750, 400 bit/s BPSK, plus guards |
| 2400.255–2400.350 | 10489.755–10489.850 | 95 kHz | SSB only (2.7 kHz) |
| 2400.350–2400.3575 (see note) | 10489.850–10489.8575 | 7.5 kHz | Broadcast, 10489.855 |
| 2400.3575–2400.365 | 10489.8575–10489.865 | 7.5 kHz | **Emergency**, 10489.860 (uplink 2400.360) |
| 2400.365–2400.490 | 10489.865–10489.990 | 125 kHz | Mixed modes (2.7 kHz) and special purpose, contests included |
| – | 10489.990–10489.997 | 7 kHz | **Multimedia beacon**, 8APSK 7200 bit/s |
| – | 10489.997–10490.000 | 3 kHz | **Upper beacon** 10490.000, CW F1A with 400 Hz shift |

- **Note:** the AMSAT-DL web table prints the broadcast uplink as "2400.3575–2400.365", the same range as the emergency slot. That is a typo; the downlink column (10489.850–10489.858) gives 2400.350–2400.3575 **[derived]**.
- **Contest zone** (since 4 Apr 2021): uplink 2400.370–2400.490, downlink 10489.870–10489.990, CW and SSB, 2.7 kHz maximum (AMSAT-DL "Contests on QO-100 allowed"). The DD1US 2023 slide also marks "FT4/8 Contest" near 10489.870.
- **Emergency frequency:** downlink 10489.860, uplink 2400.360, 2.7 kHz maximum (IARU R1 / AMSAT-DL).
- **Rules** (AMSAT-DL): full duplex is mandatory, because you must be able to monitor your own downlink. Not permitted: FM, digital FM modes (C4FM, D-STAR), gateway traffic or relaying, any signal wider than 2.7 kHz, and any operation below the lower beacon or above the upper beacon. Keep a guard band to the beacons.

Sources: <https://amsat-dl.org/en/p4-a-nb-transponder-bandplan-and-operating-guidelines/>, <https://amsat-dl.org/en/new-qo-100-band-plan/>, <https://amsat-dl.org/en/contests-on-qo-100-allowed/>, <https://www.iaru-r1.org/2020/qo-100-international-emergency-frequency/>, <https://en.wikipedia.org/wiki/Es%27hail_2>

---

## 2. Beacons

| Beacon | Downlink | Modulation | Content | Source |
|---|---|---|---|---|
| Lower | **10489.500 MHz** | CW **F1A**: constant-carrier FSK, 400 Hz shift. Changed from on-off A1A in Dec 2020 "for easier antenna alignment" | CW text "HI de Qatar-OSCAR 100 (DK0SB) …" with operating guidelines | AMSAT-DL; OEVSV wiki |
| Middle | **10489.750 MHz** | **400 bit/s BPSK**, AO-40 format | Telemetry and text in AO-40 block format | AMSAT-DL; SDR Console; AMSAT-DL tlmspec.txt |
| Multimedia | **10489.995 MHz centre**; SSB zero-beat 10489.9933 (bandplan says 10489.9935) | 8APSK, 7200 bit/s, 2.7 kHz BW (DJ0ABR HSmodem) | NB/WB spectrum and waterfall, DX cluster, CW skimmer, AMSAT bulletins | AMSAT-DL MM beacon page; DD1US 2023 |
| Upper | **10490.000 MHz** | CW F1A, 400 Hz shift (bandplan). The Dec 2020 article calls it "experimental … CW or PSK, later with sophisticated modulation" | CW identification | AMSAT-DL |

- **Origin:** the beacons come from the AMSAT-DL ground station **DK0SB in Bochum**, and the PSK beacon there is GPS-referenced. AMSAT-DL: the PSK beacon "is very frequency accurate due to a GPS reference", used for "frequency stabilization of unmodified PLL-LNBs", so that "drift of the LNB [is] compensated automatically".
- **Middle beacon framing** (AO-40 spec): 400 bit/s, differentially encoded, then XOR-ed with a 400 Hz clock (Manchester), low-pass filtered (3 dB at 560 Hz), balanced-modulated to give PSK with **no residual carrier**. Frames are sync `39 15 ED 30`, then 512 data bytes, then a 2-byte CRC.
  - **[measured 08/10, on the 07/10 recordings]** The CRC is tlmspec's CRCC = CRC-16/CCITT-FALSE (as gr-satellites checks it). DK0SB alternates an uncoded block with an AO-40 FEC frame (5200 symbols, the 65-bit distributed sync of gr-satellites' `ao40_fec_deframer` matching in full), each followed by a `00` byte and fifty `50` bytes (tlmspec says "~130" for AO-40): one uncoded block every 25.4 s, types K, L, M, N in turn. gr-satellites' QO-100 entry lists both formats on 10489.750. The decoder is ohsnb/dsp/ao40.py (uncoded only).
  - **[derived]** Because the carrier is suppressed, a frequency estimator has to remove the modulation first, for example by squaring the signal (×2) or with a Costas loop. A simple FFT peak-pick will find the ±400 Hz Manchester sidebands, not the centre.
- **Which beacon to lock to:**
  - **SDR Console** locks to the **middle BPSK beacon**. You click its centre trace to enable offset compensation, and the offset log can be saved to CSV.
  - **DJ0ABR's QO100_Transceiver** locks to the **lower CW F1A beacon**. I read the source: it looks for both F1A tones (x.500000 and x.500400) and takes the midpoint, x.500200, as the reference. Its LNB *calibration* step uses the BPSK beacon.
  - **[derived]** F1A has an always-present carrier on one of two known tones, so a 2 Hz-resolution FFT locks to it easily.
  - **[derived]** The middle beacon sits mid-band, so an IF error estimated there splits evenly across the passband, but it needs a PSK-aware estimator.
- **Always on?** No source gives a published availability guarantee for any beacon **[unverified]**. Every operating guide treats the lower CW and middle PSK beacons as permanent. Design for "beacon missing" anyway: hold the last correction and alarm.
- **Beacon level:**
  - The level is the regulatory ceiling. Nobody's downlink should exceed it.
  - DL4YHF, on the Goonhilly WebSDR, measured the "Upper Beacon (PSK)" at −68 dB and his own 3.5 W into a 60 cm mesh dish at −72 dB, i.e. 4 dB below. That was with the pre-2020 plan, when the PSK beacon was at the top.
  - A 90 cm dish typically shows the lower beacon C/N above 30 dB (BATC forum, via search summary).
  - I found no absolute EIRP figure for the beacons **[unverified]**.

Sources: <https://amsat-dl.org/en/qo-100-high-speed-multi-media-beacon/>, <https://amsat-dl.org/wp-content/uploads/2019/01/tlmspec.txt>, <https://www.sdr-radio.com/EsHail-2>, <https://wiki.oevsv.at/wiki/QO-100/QO-100_NOT-/KAT-Projekt_im_Landesverband_OE3/QO-100_Bakenmeldungen>, <https://qsl.net/d/dl4yhf/QO100/QO100.html>, DD1US 2023 slides <https://www.darc.de/fileadmin/filemounts/distrikte/p/Distrikt_P/VUS/Engen_2023/06_Dreil%C3%A4ndereck-Sysop-Treffen-2023_QO-100-How_to_become_QRV_on_the_NB_transponder__DD1US.pdf>, github.com/dj0abr/QO100_Transceiver `liquid/liquiddrv.cpp`

---

## 3. LNB setups

- **Standard PLL LNB:** 9750 MHz LO, giving an **IF of 739.5–740.0 MHz** (lower beacon at 739.500, middle at 739.750). Sources: search summary of the baltic-lab/BATC material; the WiMo "QO-100 Rx Set, IF 740 MHz"; and the BATC Goonhilly NB pipeline, which tunes its Airspy to `center_frequency=739.750250` **[read in repo]**.
- **SDR Console's QO-100 preset** uses an RX downconverter LO of **9750.225 MHz**, which bakes in a typical LNB offset. Treat it as a starting point, not a fact about LNBs.
- **Crystal:** consumer PLL LNBs use a **25 MHz** crystal (25 × 390 = 9750). Some, such as the Octagon OSLO, use **27 MHz**.
- **Reference injection:**
  - Remove the crystal and feed a GPSDO up the IF coax through an LC series circuit. "26.5–28 MHz is OK for reliable locking" on the 27 MHz Octagon (baltic-lab, via search).
  - BATC Goonhilly: a Leo Bodnar GPSDO supplies **25 MHz to the LNB** and **10 MHz to the Airspys** at the same time.
  - The DX-Patrol downconverter "supplies 25 MHz ref to LNB via 2nd cable".
  - The AMSAT-DL Downconverter V3d has a central OCXO/GPS clock for the LNB, the TX mixer and the SDR.
- **DJ0ABR's code** defaults to `LNB_REF 24000 kHz` with a ×390 multiplier, i.e. a **9360 MHz LO** when a 25 MHz-design LNB is fed 24 MHz. The GUI default comment says 739.75 MHz "for 25MHz LNB" **[read in source]**. So the LO multiple and reference are configurable in practice, and the appliance must allow arbitrary LO values.
- **Drift magnitudes:**
  - Rule of thumb: **1 ppm at 10 GHz ≈ 10 kHz** (jdow, SDR Console forum). Exactly, 1 ppm of 9750 MHz is 9.75 kHz **[derived]**.
  - Unstabilised consumer LNB crystals: "on the order of 300 PPM with temperature changes" (rtl-sdr.com on the Bullseye). That figure is a vendor-blog claim and looks high to me **[unverified]**. It is still clear that drift of tens of kHz is normal.
  - Othernet **Bullseye** (2 ppm TCXO): ±10 kHz at 23 °C, ±30 kHz over −20…60 °C, with a 25 MHz reference output on a second F connector.
  - **QRO.cz** TCXO LNB (0.2 ppm): about 3 kHz maximum error, typically ±1 kHz after 5 minutes' warm-up (WiMo listing, via search).
  - **Drift rate per °C** for ordinary LNBs: I did not find a sourced kHz/°C or ppm/°C number **[unverified]**. Measure it on the real LNB from beacon-lock logs.
- **Pull-in range:** DJ0ABR's beacon sync corrects LNB drift "in a range of 2 kHz" (AMSAT-DL Linux Transceiver page). An unmodified LNB therefore needs a coarse acquisition step, a wide FFT search over tens of kHz, before the fine lock.

Sources: <https://www.rtl-sdr.com/the-othernet-bullseye-tcxo-lnb-for-qo-100-reception/>, <https://www.wimo.com/en/qo-100-10ghz-lnb-qro-cz>, <https://forum.sdr-radio.com/viewtopic.php?p=10393>, <https://wiki.batc.org.uk/Es%27hail-2_Ground_Station>, <https://kittenlabs.de/blog/2019/04/27/eshail-2-transceiver-setup/>

---

## 4. Pluto-family hardware

### Simultaneous TX at 2400 and RX at about 739.75 MHz

- The AD9361/AD9363 has **separate RX and TX synthesizers**. The ADI Linux driver exposes `altvoltage0` (RX_LO) and `altvoltage1` (TX_LO), each with its own `frequency`, `external`, `powerdown` and fastlock attributes. In `ad9361_synth_lo_powerdown()`, channel 0 is RX and channel 1 is TX **[read in analogdevicesinc/linux drivers/iio/adc/ad9361.c]**.
- **RX and TX share one baseband sample rate.** DJ0ABR's code says "tx sample rate (must be same as RX samp rate)".
- In DJ0ABR's working configuration the RX LO is about 739.x MHz and the TX LO is 2399.970 MHz. The RX LO is put 30 kHz below the lower beacon and the TX LO 30 kHz below 2400.000.
- **Stock tuning range:** the ADALM-Pluto default is AD9363 at 325–3800 MHz, so both 739 MHz and 2400 MHz are in range without any hack. Setting `compatible=ad9364` (or ad9361) extends it to 70–6000 MHz (ADI wiki, "customizing").

### Sample rates

- **Minimum ADC clock** is `MIN_ADC_CLK 25000000` and the fixed decimation is ×12, so the lowest rate without the FIR is **25 MHz / 12 = 2.083 MS/s**. With the ×4 FIR decimation/interpolation enabled it is **25 MHz / 48 = 520.833 kS/s** **[driver source; matches MathWorks]**. The ADI spec page quotes "61.44 MSPS – 65.1 kSPS" for the whole range.
- **DJ0ABR's approach:** configure 3 MS/s, then call `ad9361_set_bb_rate(dev, SAMPRATE)` (from **libad9361**), which loads a suitable FIR and sets the low rate. In the current source `SAMPRATE` is **560000** (560 kS/s); its comments still say 1.12 MS/s. The buffer is `SAMPRATE/10`, i.e. 100 ms.
- **[derived]** 560 kS/s covers the whole 500 kHz NB passband with margin and is the de-facto choice.
- On Debian, `libad9361-0` and `python3-ad9361` 0.3 are packaged (see §8), so the same `ad9361_set_bb_rate()` approach is available from Python.

### Clock, TCXO and corrections

- **Oscillator:** ADI hardware page: "Rakon 1.8V RXO3225M 40MHz". Commonly quoted as **±25 ppm**, with "no TCXO used, so the frequency accuracy is only 25 PPM" (ab9il/rigpix, via search). ADI's own spec page as fetched gives no ppm figure **[partly unverified]**.
- MathWorks: two Plutos measured −7.3 to −8.2 ppm apart.
- **[derived]** Error at 2400 MHz is 2.4 kHz per ppm, so 25 ppm is up to ±60 kHz. At 739.75 MHz it is 0.74 kHz per ppm.
- **Calibration:** the `ad9361-phy` attribute `xo_correction` (and `xo_correction_available`), persistable with `fw_setenv xo_correction <Hz>`. ADI wiki, MathWorks and the driver source all show it.
- **External clock:**
  - Rev D (2021 onwards) has internal U.FL clock-in and clock-out connectors, set up through `refclk_source`.
  - Rev C was never released.
  - Kittenlabs reconfigured a Pluto through the bootloader to run from a 27 MHz GPS reference shared with the LNB.
  - DD1US: "Internal 40 MHz TCXO needs to be replaced by a better TCXO or by an external reference."
  - ZS6YI used a GPSDO as an external 40 MHz reference.
- **Variants:**
  - **Pluto+:** Zynq-7010, AD9363 (configurable as AD9361 or AD9364), 2R2T, **Gigabit Ethernet**, USB OTG, microSD boot. I found no sourced external-clock spec **[unverified]**. Its 0.5 ppm TCXO claim comes from vendor listings ("OpenSourceSDRLab … 0.5ppm TCXO") **[vendor claim]**.
  - **LibreSDR:** XC7Z020-2, AD9363 run as AD9361 (70 MHz–6 GHz), VCXO "support PPS or 10MHz tame", GbE, USB-C OTG, TF card (sdr-radio.com). Tech Minds found its oscillator held QO-100 without drift, but saw a **centre spike in DATV TX** that the Pluto did not show (rtl-sdr.com).
  - **"Pluto nano":** I could not find a reliable specification **[unverified]**. Identify it at runtime from `iio_info` (`hw_model`, `ad9361-phy` presence, `xo_correction`) rather than by product name.

### libiio URIs

- `ip:192.168.2.1` is the default USB-Ethernet gadget address. DJ0ABR's `pluto_finder.cpp` also parses `[usb:...]` from scan output.
- Also `ip:pluto.local` and `usb:<bus>.<dev>.<n>` (standard libiio forms).
- Networked units (Pluto+, LibreSDR, or a Pluto with a USB-Ethernet dongle) use `ip:<addr>`.
- Use `iio_info -s` to scan.

### TX output power and gain

- **Range:** `hardwaregain` on the TX channel runs **0 to −89.75 dB in 0.25 dB steps**. The driver has `MAX_TX_ATTENUATION_DB 89750` mdB, and MathWorks says the same.
- **Maximum output:** about **+6.5 dBm** (kittenlabs, single source). The ADI spec page's "Maximum Output Power" value did not come through in my fetch **[unverified beyond that]**.
- DJ0ABR clamps `txpower` to ≤ 0 and treats −40 as "PTT off". In the F5OEO firmware (2021 or later), `hardwaregain = −40` releases the GPO PTT lines.
- **[derived]** A driver PA is required. AMSAT-DL's PA for SDR transceivers has 46 dB gain, P1dB 35 dBm (3 W) and Psat 38 dBm (6 W) (DD1US).

### LO leakage, DC offset, and why the TX LO is offset

- In a zero-IF transmitter, LO leakage and I/Q DC offset put a carrier at the LO frequency. The usual cure is to tune the LO away from the wanted signal and shift the signal back digitally with an NCO (libre.space and Aaronia discussions).
- **[derived]** DJ0ABR puts the TX LO at 2399.970 MHz, 30 kHz below the band edge, so whatever leaks lands *outside* the transponder passband. Treat that as the reason to copy.
- **[derived]** Never leave the TX LO inside 2400.000–2400.500 while "idle". When not transmitting, power the LO down (`out_altvoltage1_TX_LO_powerdown=1`) or set maximum attenuation, so leakage does not reach the satellite.

### TX buffer underrun

- I found no authoritative statement of what the Pluto DAC outputs on a DMA underflow, whether zeros or a repeat of the last buffer **[unverified]**.
- **[derived]** Design defensively:
  - Keep the TX stream fed continuously with zeros between overs.
  - Size the buffers at about 100 ms, as DJ0ABR does.
  - On PTT-off, set −89.75 dB and/or power down the TX LO.
  - Test underflow on the bench with a spectrum analyser before going on air.

Sources: <https://wiki.analog.com/university/tools/pluto/devs/specs>, <https://wiki.analog.com/university/tools/pluto/hacking/hardware>, <https://wiki.analog.com/university/tools/pluto/users/customizing>, <https://www.mathworks.com/help/comm/plutoradio/ug/baseband-sampling-rate-and-filter-chains.html>, <https://www.mathworks.com/help/comm/plutoradio/ug/frequency-correction-for-adalm-pluto-radio.html>, <https://github.com/analogdevicesinc/linux/blob/main/drivers/iio/adc/ad9361.c>, <https://kittenlabs.de/blog/2019/04/27/eshail-2-transceiver-setup/>, <https://www.sdr-radio.com/libresdr>, <https://www.rtl-sdr.com/tech-minds-reviewing-the-libresdr-zynqsdr-70-mhz-to-6-ghz-plutosdr-clone/>

---

## 5. How existing software does beacon lock and TX correction

### DJ0ABR QO100_Transceiver (github.com/dj0abr/QO100_Transceiver, last commit 18 Nov 2024; I read the source)

- **Architecture:** a C++ backend on Linux or Raspberry Pi talks to the Pluto over libiio and to a C#/Mono GUI over UDP. The GUI is desktop, not web.
- **Beacon lock algorithm** (`liquid/liquiddrv.cpp`), applied to RX only:
  1. NCO-mix the region x.499200 … x.501200 (2 kHz around the lower beacon) to baseband.
  2. 4th-order elliptic IIR low-pass.
  3. Decimate the 560 kS/s stream by `SAMPRATE/4000` to 4 kS/s, using a Kaiser FIR decimator.
  4. FFT of length 2000, giving **2 Hz/bin**, with a new estimate about every 0.5 s.
  5. Take the magnitude, find the maximum, and take the lowest and highest bins above **½ max**.
  6. If they are more than 380 Hz apart (both F1A tones seen), the beacon centre is their midpoint. The offset is that centre minus 500200 Hz.
  7. The offset is added to the RX downmixer NCO and sent to the GUI ("Drift: n Hz").
- **TX is not corrected by the beacon lock.** TX correction comes from the Pluto reference calibration (`refoffset`, added to both RX and TX LO settings) and from a manual "calibrate LNB" step: click the BPSK beacon centre to put it on the 0 Hz line.
- **Pluto settings in that code:** RX `rf_bandwidth` 1 MHz, TX `rf_bandwidth` 0.1 MHz, RX port A_BALANCED, TX port A, gain control `slow_attack`.

### SDR Console (Simon Brown)

- **Geostationary beacon:** View → More Options → Geostationary beacon. Click the centre of the BPSK beacon at 10489.750 to enable offset compensation. Offsets can be saved to CSV.
- **Converter preset:** RX 9750.225 MHz, TX 8089.5 MHz.
- **"Sync RX":** TX tracks RX frequency and mode.
- I found no documented automatic TX correction from the own downlink; operators compare their own signal with the beacon by ear or eye **[as far as found]**.

### F1ATB Remote SDR (web-based, Pluto)

- Tracks the upper and lower beacons to estimate the LNB correction.
- **Semi-automatic TX correction (v4.3 and later):** transmit a **sine at 800 Hz** in SSB, measure the frequency of the strongest signal in the receive chain, and correct the transmitter until the received tone is at 800 Hz. You start it by pressing button A for a while.
- Caveat in its own docs: it stops if the browser tab is hidden, because the processing is client-side.

### Others

- **F5OEO** QO-100_SSB-WebSDR_DATV-WebSpectrum (Pluto firmware plus web UI) has beacon-lock changes for the new bandplan; details not read.
- **SDRangel, OpenWebRX, ExpertSDR:** I found no QO-100-specific self-monitoring TX lock documentation **[unverified / not found]**.

### [derived] Error model for a self-correcting design

- Let the RX-side error be ε_R = LNB_err + Δ_sat + PlutoRef_ppm × f_RXLO.
- **Beacon lock** measures the beacon's downlink offset, which equals ε_R. The beacon is GPS-accurate at uplink.
- **Own-signal lock:** with a known tone or CW carrier at intended uplink f_u, the measured downlink offset after beacon correction equals the **TX absolute error** (PlutoRef_ppm × 2400 MHz), because Δ_sat affects the beacon and you identically.
- So the correct procedure is:
  1. Beacon-lock RX.
  2. Measure your own carrier against the bandplan grid.
  3. Correct the TX NCO, or update `xo_correction`, which also moves the RX LO but proportionally.
- The **transponder round trip** is about 0.25 s (geostationary). This is inferred and should be checked; it is not from a source here. Average over several FFT frames and use a slow loop.

Sources: <https://amsat-dl.org/en/qo-100-linux-transceiver/>, <https://github.com/dj0abr/QO100_Transceiver>, <https://www.sdr-radio.com/EsHail-2>, <https://f1atb.fr/?p=3446>, <https://github.com/F5OEO/QO-100_SSB-WebSDR_DATV-WebSpectrum>

---

## 6. Modes actually used on the NB transponder

**Modes listed by DD1US (2023):** SSB, CW, FreeDV (including 2020), RTTY, SSTV/KGSTV, FAX, Feldhell, PSK31, FT8, FT4, THOR8, ROS, QRA64D, JT65A, Robust Packet, VARA, Winlink, and the AMSAT-DL HSmodem (up to 7200 bit/s in 2.7 kHz).

| Mode | Frequency (downlink) | Source and notes |
|---|---|---|
| FT8 | **10489.540** dial; activity seen at 10489.540–10489.543 | Search summary (sigidwiki/TBR AN-1). 10489.540 is the bottom edge of the 500 Hz digimode segment, so FT8 audio at about 0–3 kHz runs into the 2.7 kHz segment. **[unverified as a formal calling frequency]** |
| FT4 / FT8 contest | about 10489.870 | DD1US bandplan slide marks "FT4/8 Contest" at the start of the contest zone |
| JS8Call | **10489.548 USB** (uplink 2400.048) | OH8STN, Feb 2026: a "commonly used trial spot" |
| FreeDV | **10489.640** | FreeDV Activity Day announcement (Aug 2026). Modes on QO-100 in sources: **1600 and 2020** (Lime community article); 700D also cited. No source gives a QO-100 mode convention for 700E or RADE **[unverified]** |
| CW | 10489.505–10489.540 segment, plus the contest zone | No conventional CW calling frequency found **[unverified]** |
| Emergency | 10489.860 | IARU R1 |
| PSK31, RTTY, SSTV, Q65, Olivia, MFSK, Hell, WSPR, M17 | No documented calling frequencies found **[unverified]** | Narrow modes belong in 10489.540–.580 (≤500 Hz); wider digital in .580–.650 (≤2.7 kHz) |

- **Prohibited:** FM, and digital FM voice (D-STAR, C4FM). M17 is 4FSK FM-based, so by the same "no digital FM modes" rule it is effectively excluded. That is my reading; I found no explicit AMSAT-DL ruling on M17 **[derived]**.
- **FreeDV versions:** FreeDV 2.0.0 (RADE V1, ML-based, 1500 Hz BW) was released **June 2025** after previews in Oct 2024 and Jan 2025 (freedv.org). Debian trixie ships freedv **1.8.11**, which has no RADE.

Sources: DD1US 2023 slides, <https://oh8stn.org/blog/2026/02/17/js8call-on-qo-100-sat-narrowband-a-complete-frequency-guide-for-s51sg/>, <https://groups.google.com/g/digitalvoice/c/wyaKF-Lg7HM>, <https://freedv.org/freedv-2-0-0-released/>, <https://limemicro.com/community/digital-voice-transmission-via-qo-100-with-freedv-mode-2020/>

---

## 7. Public spectrum and WebSDR streams (BATC/AMSAT-UK, Goonhilly, IO70JB)

### Hardware

- Two Airspy receivers locked to a Leo Bodnar GPSDO (10 MHz to the Airspys, 25 MHz to the LNB).
- RX chain: 1.3 m dish, then a GPS-locked Octagon LNB, then the Airspy.
- Software stack: Ubuntu 18.04 and nginx.

### NB WebSDR at <https://eshail.batc.org.uk/nb/>

- **Software:** PA3FWM's WebSDR, which is closed-source.
- **Pipeline** (`eshail-ghy-nb-resample-airspy`):
  - `airspy_rx` at 2.5 MS/s, centre **739.750250 MHz**.
  - csdr interpolate/decimate ×2/5, ×4/5, ×16/25 to **512 kS/s** (converted to u8 and fed to the WebSDR as an `rtlsdr` TCP device).
  - The published `websdr.cfg` (2019) has `samplerate 512000` and `centerfreq 10489675`. The stale centre frequency suggests the cfg repo is not current **[derived]**.
- **Websocket endpoints** (from the shipped JS): audio `wss://eshail.batc.org.uk/~~stream?v=11`, waterfall `wss://…/~~waterstream<band>?format=…&width=…&zoom=…&start=…`.
  - On 2026-10-04 the audio endpoint upgraded to a websocket (HTTP 101) for me **[tested]**.
  - The protocol is PA3FWM's own, compressed and **undocumented**, so a client would have to reverse-engineer `websdr-sound.js`. Not a sensible dependency.

### WB spectrum, `wss://eshail.batc.org.uk/wb/fft`

Source: `eshail-ghy-wb-fft-airspy/main.c`, which I read, plus a live test.

- **Subprotocols:** `fft` (every 250 ms), `fft_fast` (every 100 ms), `fft_m0dtslivetune`, `fft_f5oeoplutofw`, `fft_ea7kirsatcontroller`.
- **Frame format:** binary websocket frames of **922 × uint16 little-endian**, 1844 bytes. This is a 1024-point FFT (Hann window, smoothing 0.9995) keeping bins 5–95 %, scaled and floor-compensated, clipped at 0xFFFF.
- **Coverage:** Airspy at 745 MHz centre, 10 MS/s, so the 922 bins cover about **10490.5–10499.5 MHz** (9 MHz). The web client uses `_start_freq = 490.5` and a 9 MHz span.
- **Live test 2026-10-04 [tested]:**
  - `fft`: 22 frames in about 6 s.
  - `fft_fast`: 55 frames in about 6 s.
  - All frames 1844 bytes.
- **There is no equivalent documented NB FFT websocket**; the NB view comes only through PA3FWM's waterfall stream.

Sources: <https://wiki.batc.org.uk/Es%27hail-2_Ground_Station>, github.com/BritishAmateurTelevisionClub/{eshail-ghy-wb-fft-airspy, eshail-ghy-nb-resample-airspy, eshail-ghy-nb-websdr-cfg, eshail-ghy-web}

---

## 8. Debian 13 trixie packages (checked locally with apt-cache, 2026-10-04)

| Need | Package | Version | Notes |
|---|---|---|---|
| numpy | python3-numpy | 1:2.2.4+ds-1 | |
| scipy | python3-scipy | 1.15.3-1 | |
| libiio | libiio0, libiio-utils, python3-libiio | **0.26-2** | libiio **0.x API**, not 1.0. Utils: iio_info, iio_attr, iio_readdev, iio_writedev, iio_reg, iio_genxml, iio_stresstest |
| ad9361 helper | libad9361-0, python3-ad9361 | 0.3-2+b2 | Provides `ad9361_set_bb_rate()` (FIR for <2.083 MS/s) |
| pyadi-iio | – | **not packaged** | pip only |
| SoapySDR | python3-soapysdr, soapysdr-tools | 0.8.1-5+b2 | |
| Soapy modules | rtlsdr 0.3.3, airspy 0.2.0, hackrf 0.3.4, uhd 0.4.1; also bladerf, lms7, remote, audio, … | | **No SoapyPlutoSDR, no SoapySDRPlay** packaged. Use libiio directly for Pluto; SDRplay needs the vendor API plus a source build |
| GNU Radio | gnuradio, libgnuradio-iio3.10.12 | 3.10.12.0-1 | gr-iio is in-tree |
| WSJT-X | wsjtx | **2.7.0+repack-1** (installed) | Ships `jt9`, `ft8code`, `ft4code`, `ft8sim`, `q65code`, `q65sim`, `wsprd`, `jt9code`, `msk144code`, … (`ft4sim` absent; `ft4sim_mult` present) |
| JS8Call | js8call | 2.2.0+ds-5+b1 (installed) | |
| codec2 | codec2, libcodec2-1.2 | **1.2.0-3** | The `codec2` CLI package has **only** c2enc, c2dec, fdmdv_mod/demod, fdmdv_*_test_bits, fsk_mod. **No `freedv_tx` / `freedv_rx`** |
| FreeDV GUI | freedv | 1.8.11-1+b5 | No RADE |
| fldigi | fldigi | 4.2.06-1+deb13u1 | |
| multimon-ng | multimon-ng | 1.3.1+dfsg-1 | |
| Audio | libportaudio2 19.6.0, python3-pyaudio 0.2.13, alsa-utils 1.2.14 | | **python3-sounddevice not packaged** (pip, uses libportaudio2) |
| Websocket client | python3-websockets 15.0.1, python3-aiohttp 3.11.16 | | |
| Not in trixie | sdrangel, openwebrx, csdr | | |
| Also present | satdump 1.2.2-1, gqrx-sdr 2.17.6 | | |

### FreeDV through libcodec2 [local, tested with ctypes]

- `libcodec2.so.1.2` exports `freedv_open`, `freedv_tx`, `freedv_rx`, `freedv_nin`, `freedv_get_n_speech_samples`, `freedv_get_modem_sample_rate`, etc.
- It is built with LPCNet (`freedv_2020x_open` present), so 2020 is available.
- `freedv_open()` succeeded for these modes:

| Mode | Modem rate (S/s) | Speech samples per frame |
|---|---|---|
| 1600 | 8000 | 320 |
| 700C | 8000 | 640 |
| 700D | 8000 | 1280 |
| 700E | 8000 | 640 |
| 2020 | 8000 | 2880 |
| 2020B | 8000 | 1440 |
| 800XA | 8000 | – |
| 2400A / 2400B | 48000 | – |

- Mode constants from codec2 1.2.0 `freedv_api.h`: 1600=0, 2400A=3, 2400B=4, 800XA=5, 700C=6, 700D=7, 2020=8, 700E=13, 2020B=16.
- **[derived]** FreeDV can be driven from Python via ctypes without the missing CLI tools.

### jt9 command-line decoding [local, tested]

```
ft8sim "CQ G4XYZ IO91" 1500 0 0 0 1 -10      # writes 000000_000001.wav (12000 Hz, 16-bit, mono, 15.0 s)
jt9 -8 -d 3 000000_000001.wav               # --ft8; decodes in ~1.3 s on this host
# stdout: 000001 -10  0.0 1500 ~  CQ G4XYZ IO91
#         <DecodeFinished>   0   1        0
```

- **Flags:** `-8/--ft8`, `-5/--ft4`, `-3/--q65`, `-W/--fst4w`, `-d 1..3` depth, `-L/-H` frequency limits, `-f` RX offset, `-a`/`-t` data and temp paths, `-c/-G/-x/-g` for AP decoding.
- jt9 also writes `decoded.txt`, `jt9_wisdom.dat` and `timer.out` into the current directory, so run it in a per-job temp dir or pass `-a`/`-t`.
- It takes the UTC time from the file name (HHMMSS).
- **Input WAV:** 12000 Hz, 16-bit, mono. FT8 is a 15 s slot; FT4 is 7.5 s by protocol.
- The `-5` FT4 path was not tested end-to-end, because `ft4sim` is not shipped.

### ft8code prints channel symbols [local, tested]

`ft8code "CQ G4XYZ IO91"` prints:

- the 77-bit source-encoded message;
- the 14-bit CRC;
- the 83 parity bits;
- **"Channel symbols (79 tones)"**: three Costas sync blocks `3140652` plus 2 × 29 data symbols, each a tone index 0–7.

So it can generate TX tone sequences (6.25 Hz tone spacing at 160 ms/symbol, per FT8 protocol). `ft4code` exists for FT4.

---

## 9. Licence and operating constraints

- **Beacon-level rule** (AMSAT-DL): "No uplinks should result in downlink signals that are stronger than these beacons … keep your signal below Beacon level."
- **LEILA:** signals that break the rule "will be marked by a 'LEILA' siren. When they have been marked by 'LEILA', operators should immediately reduce their uplink power (ERP)." Wikipedia also describes LEILA as a power-monitoring alert system. Its threshold and full name are still not found in a source **[unverified]**.
- **LEILA's siren, measured [tested, on real recordings]** - sources: Brian's receive IQ recordings `openhamshack-nb-20261017-154145Z-10489.540MHz-FT8` and `openhamshack-nb-20261017-154414Z-10489.540MHz-FT8` (17/10/2026, NB on the Mac, the box's Pluto, receive only, during the 7P8GE FT8 pile-up; he heard the siren twice). Three sirens are in them, and three more in two later recordings of the same session:

  | UTC | tones (MHz) | apart | lasted |
  | --- | --- | --- | --- |
  | 15:41:58.4-15:42:03.6 | 10489.540016 / .540229 | 213 Hz | 5.2 s |
  | 15:43:36.0-15:43:42.1 | 10489.541298 / .541504 | 206 Hz | 6.1 s |
  | 15:44:28-15:44:31 | 10489.540444 / .540650 | 205 Hz | at least 2.5 s (its start is under the pile-up) |
  | 15:47:42-15:47:46 | 10489.541175 / .541388 | 213 Hz | about 3.6 s |
  | 15:53:28-15:53:33 | 10489.542398 / .542604 | 206 Hz | about 4 s |
  | 15:55:04-15:55:10 | 10489.541178 / .541385 | 207 Hz | at least 6 s (the excerpt checked was 6 s) |

  The last three are in two later recordings of the same session, `openhamshack-nb-20261017-154554Z-10489.540MHz-FT8` and `openhamshack-nb-20261017-155205Z-10489.818MHz-USB` (the second tuned to SSB, so they were found by the detector, not heard), and were checked by hand from the IQ afterwards.

  - **Waveform:** two steady, unmodulated tones taking turns, each on for **200 ms** (a 400 ms cycle, 2.5 per second), switched hard (the change is complete within 10 ms), constant amplitude. A two-tone "hi-lo" siren, **not** a swept or warbling tone: the frequency of each tone holds to within a few hertz while it is on.
  - **Level:** the siren's power is about **2 dB above the middle beacon's** total power, both times it was measured carefully (+2.0 and +2.1 dB, 15:43:36 and 15:44:28; the live detector's coarser estimate reads +3.5 to +5.5 dB on the same sirens).
  - **When and where:** in the FT8 slot *after* an over, while the offender is silent, a second or so after the slot ends. At 15:44:28 the pair is centred on a strong signal of the previous slot (10489.5405-.5406 MHz, the strongest station there); at 15:43:36 no single station of the previous slot is clearly under it.
  - **What it does not tell:** what LEILA measures. By any measure tried (strongest bin against the beacon's, power in 50 Hz, power in a beacon-wide slice) many of the pile-up's callers were over the beacon in those minutes, and only six sirens sounded in 13 minutes, all in or beside the FT8 window. The threshold, and how LEILA picks whom to mark, remain **[unverified]**.
  - The app's detector (`ohsnb/dsp/overpower.py`, `Siren`) was built on the first three. Replayed over all five recordings of the session (154145Z, 154414Z, 154554Z, 154820Z, 155205Z: 800 s, two FT8 pile-up stretches and a 5-minute SSB one), it finds those three and the three later ones, and nothing else. `tests/test_overpower.py` runs it on 4 kS/s excerpts of the first two recordings (`tests/data/leila-sirens.npz`).
- **The three beacons are about equally strong; BATC's NB WebSDR is not flat [tested, 17/10/2026]** - sources: Brian's recording `openhamshack-nb-20261017-163511Z-10489.540MHz-FT8` (IQ library `20261017-mac-nb-qo100-qo100-nb-163511`, 600 s, the box's Pluto at 1.2 MS/s, DC 3.5-3.9 kHz below the middle beacon as NB tunes it) and the WebSDR's own S-meter (2.7 kHz USB, 20 readings a dial, ~22:50 UTC).
  - In the recording, each beacon's power over the noise in 2.7 kHz (60 one-second spectra): lower -1.0 dB, upper -1.1 dB against the middle (sd 0.1); NB's own over-power arithmetic (1 kHz slices) gives -0.7 / -0.7.
  - The WebSDR reads lower -6.9, upper -6.6 against the middle, whichever audio pitch the tones are put on - but its noise floor has the same shape: -86.7 dB from .700 to .800, -88.6 at .600 and .900, -92.2 at .505 and .985. Each beacon over the WebSDR's noise beside it: lower 10.1, middle 11.7, upper 10.6 dB, i.e. -1.6 and -1.1 against the middle, as in NB's recording. The ~5.5 dB is the WebSDR's passband hump (if it were the transponder's, a receiver whose own noise dominates, as ours does, would see the CW beacons 5.5 dB down too).
  - Nothing near the Pluto's DC takes anything off: the recording's noise floor within +-1 kHz and 2-5 kHz of DC equals the floor 60-150 kHz away to 0.1 dB, and every stage after the LNB's first amplifier shapes that noise exactly as it shapes a signal. (With no LNB signal, 13/10/2026, the Pluto's own floor rises 7.8 dB within +-1 kHz of DC, still 28 dB under the LNB's noise.)
  - So: compare a signal with the beacon on one receiver, never powers across two, and on the WebSDR only near the middle beacon. A WebSDR reading taken at 10489.540 is ~4 dB low against its middle beacon (its floor is -90.8 there).
- **How far over the beacon the 163511 pile-up was [tested]:** in the raw IQ, the FT8 window (10489.540-.543) held 14-21 dB more power than the middle beacon, with 9-26 FT8 signals within 10 dB of it, and the strongest single one was **8-12.6 dB over the beacon's total power** (50 Hz against the beacon's 3 kHz). NB's over-power watch read +9 to +19 dB there, in hits 1.5-3 kHz wide: its 1 kHz slice adds up several callers, so the excess describes the pile-up rather than one station - but its strongest station really was ~11 dB over. The LEILA sirens' "about 2 dB over the beacon" above stands: the beacon was not under-read.
- **Typical uplink power from sources:** "5–10 W PEP" with 22.5 dBi (75 cm dish) (Wikipedia); "around 2 W" with 60–80 cm and the PA at the dish (vendor guidance, via search); about 4 W with a POTY feed (BATC forum, via search). The exact EIRP needed depends on bandwidth, and no single sourced dBW figure was found **[unverified]**.
- **Bandwidth** at most 2.7 kHz. No FM or digital FM. No gateways or relays. Full duplex is mandatory.
- **UK licensing:** 2400–2450 MHz amateur satellite allocation (secondary) under Ofcom. I did not research the licence conditions themselves **[out of scope / unverified]**.

---

## Decisions this suggests

1. **Sample rate 560 kS/s via `ad9361_set_bb_rate`** (python3-ad9361), with RX and TX sharing it. That covers the whole 500 kHz NB passband with one RX stream; channelise in numpy.
2. **TX LO outside the passband, for example 2399.970 MHz** (DJ0ABR's choice), with the signal placed by an NCO. Power the TX LO down or set −89.75 dB whenever PTT is off, and keep the TX stream fed with zeros during overs.
3. **Configure the RX LO from the LNB LO.** Accept arbitrary LNB LO and reference values (9750 / 25 MHz is common, but 27 MHz Octagons and 24 MHz-fed setups that give 9360 MHz exist). Show the measured offset, not an assumed one.
4. **Two-stage beacon lock.**
   - Coarse: FFT over ±50 kHz around the expected beacon, for unmodified LNBs.
   - Fine: use **both** the lower F1A beacon (tone pair x.500000/x.500400, midpoint method, about 2 Hz bins) and the middle BPSK beacon (squaring or Costas estimator).
   - Cross-check them: they should agree within a few Hz.
   - Hold the last correction and alarm if both disappear.
5. **Own-signal TX correction after RX lock.** Send a short carrier or tone (F1ATB's 800 Hz method), measure it on the beacon-corrected downlink, and update a TX NCO offset (or `xo_correction`). Average over several frames to ride out the round trip. Gate it behind an operator action and keep the power low (below beacon).
6. **Beacon-relative level meter.** Compute the own downlink level against the measured beacon level continuously. Make "above beacon" a hard TX interlock or warning: this is the licence condition, and LEILA enforces it.
7. **Clocking.** Support a shared GPSDO reference (LNB 25/27 MHz plus SDR reference) as a first-class configuration. On a stock Pluto (±25 ppm, up to 60 kHz at 2.4 GHz) the TX correction step is essential, not optional.
8. **Decoders.**
   - Use `jt9 -8 -d 3` (and `-5` for FT4) on 12 kHz 16-bit mono 15 s WAVs, one temp dir per slot. TX tones come from `ft8code`/`ft4code`.
   - Use **libcodec2 1.2 via ctypes** for FreeDV 700D/700E/1600/2020, because Debian has no `freedv_tx`/`freedv_rx`.
   - JS8Call and fldigi are available as packages if needed.
9. **Use libiio 0.26 Python bindings directly for Pluto.** Do not plan on SoapyPlutoSDR, which is not packaged. Use SoapySDR only for the optional RX-only SDRs: RTL, Airspy, HackRF, UHD are packaged; SDRplay is not.
10. **External reference spectrum.** The BATC WB FFT websocket is simple and documented in code (922 × u16 LE, 10490.5–10499.5 MHz). The NB WebSDR protocol is proprietary, so do not build on it. If a remote NB reference is wanted, use it only as a human-facing link.
