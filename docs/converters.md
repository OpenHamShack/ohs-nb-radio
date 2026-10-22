# Converters — model and sources

OpenHamShack QO-100 NB and OpenHamShack Radio share one list of converter definitions
(`ohscore/converters.py`): transverters, LNBs and up/down-converters between
the radio and the air. Brian asked for it on 07/10/2026 after showing SDR
Console's **Converter Definitions** window; the fields, the two preset
packs and the wording follow that window so an operator coming from SDR
Console recognises them.

## The model

| field | stored as | meaning |
| --- | --- | --- |
| Title | `title` | unique (ignoring case); bands and paths name their converter by it |
| Type | `type` `down` / `up` | down: the radio sits below the air frequency; up: above |
| Use | `use` `rx` / `tx` / `rxtx` | RX only; TX only (only transmitted through); RX/TX (a transverter) |
| RX offset | `rxOffset` Hz | used on receive (a TX-only one stores its TX offset here; nothing reads it) |
| TX offset | `txOffset` Hz | used on transmit (a transverter's equals its RX offset); required for TX only |
| Inverted | `inverted` | high-side LO: the spectrum is mirrored (not in SDR Console) |
| Most drive | `maxDriveDbm` | the most a transmitting converter's input takes, dBm (not in SDR Console) |

```
down, not inverted:  radio = air - offset
up,   not inverted:  radio = air + offset
inverted (either):   radio = offset - air     USB <-> LSB, tuning reversed
```

A mixer gives LO + f and |LO − f|, so there is one inverted product; for
an inverted converter the type only says which side of the air the radio
lands on, and `Converter.check()` holds it to that.

### Use, and which way "down" means

`use` replaced a bool, `rxtx`, on 07/10/2026, when Brian asked for **TX
only**: Ray transmits with an IC-9700 through an uplink upconverter and
receives with an SDR, so his upconverter is never in a receive path. A
definition stored before has `rxtx` and loads as the same converter (true:
`rxtx`, false or missing: `rx`); it is written back with `use` and without
`rxtx`. With both keys (a hand edit), `use` wins. A release from before
reads the missing `rxtx` as receive only and refuses to transmit through
anything until it is set again - a downgrade fails closed.

The type is where the radio sits, and its *name* is SDR Console's, from the
receive direction: an LNB or a transverter brings the air **down** to the
radio. That reads backwards for something that only transmits: the QO-100
uplink upconverter has the radio at 1296 MHz, below 2400 MHz on air - type
down - and is an **up**-converter. So a TX-only definition is named by its
transmit direction (`Converter.kind()`): the edit form's Type buttons and
the list's Up/Dn column say **Up** for it. Only the name changes; the
stored type and the formula are the same, so no frequency moves.

A TX-only converter:

- is never received through: NB refuses it as the LNB with a sentence
  (also from a hand-edited file, which falls back on load to an LNB that
  works); a HAM band set to one is **received directly** and transmitted
  through it;
- is treated exactly as an RX/TX one for everything transmit: its TX
  offset, its most drive (required in HAM, as for RX/TX), HAM's drive cap
  and key-up checks. HAM's transmit-side lookups include it by default and
  receive asks for the receive one explicitly, so a path that forgets to
  ask still meets the drive cap.

## Presets and where each number comes from

Every value is a published product LO or a convention printed by SDR
Console. Combinations whose LO could not be read in a manufacturer's (or
SDR Console's) own text were left out rather than worked out: 4 m on a
28 MHz IF, 432 or 2320 MHz on 144, 10 GHz. No preset carries a drive
limit: that figure has to come from the operator's own transverter.
Looked up 07/10/2026.

### "+ VHF/UHF/SHF" (both apps)

| title | offset | source |
| --- | --- | --- |
| 50 MHz (28 MHz IF) | 22 MHz | Elecraft XV50 (Elecraft XV-series transverters, PNWVHFS 2006 notes: <https://pnwvhfs.org/conference/2006/elecraft-transverters.html>) |
| 144 MHz (28 MHz IF) | 116 MHz | Elecraft XV144, owner's manual (<https://ftp.elecraft.com/XV/Manuals%20Downloads/E740096%20XV%20Transverter%20Owner's%20Manual%20Rev%20F1.pdf>); SDR Console's help text ("144–146 MHz … 28–30 MHz, 116 MHz lower") |
| 432 MHz (28 MHz IF) | 404 MHz | Down East Microwave L432-28 (RF 432 / IF 28 / LO 404, <https://community.flexradio.com/discussion/comment/18283975>) |
| 1296 MHz (28 MHz IF) | 1268 MHz | SDR Console's "+ VHF/UHF/SHF" pack (Brian's screenshot, 07/10/2026); Kuhne TR1296H28 (<https://rigpix.com/transverters/kuhne_tr1296h28.htm>) |
| 1296 MHz (144 MHz IF) | 1152 MHz | SDR Console's pack (screenshot) |
| 2304 MHz (28 MHz IF) | 2276 MHz | SDR Console's pack (screenshot) |
| 2304 MHz (144 MHz IF) | 2160 MHz | SDR Console's pack (screenshot) |
| 3400 MHz (144 MHz IF) | 3256 MHz | Down East Microwave MINI3400, 3400 MHz with a 144 MHz IF, low-side (<https://downeastmicrowave.com/product-p/mini3400.htm>) |
| 5760 MHz (144 MHz IF) | 5616 MHz | Down East Microwave 5760-144 (<https://www.downeastmicrowave.com/product-p/5760-144.htm>) |
| HF upconverter (125 MHz) | 125 MHz, up, RX only | NooElec Ham It Up: 125 MHz LO (<https://www.rtl-sdr.com/nooelec-releases-the-ham-it-up-nano-hf-upconverter/>) |
| HF upconverter (120 MHz) | 120 MHz, up, RX only | Airspy SpyVerter R2: 120 MHz (<https://airspy.com/spyverter-r2/>) |

Every transverter found is low-side (not inverted). The DEMI 3400 and
5760 pages name the band and IF; their LO is the low-side difference.

SDR Console's help text also uses a 150 MHz HF upconverter as its example
of an up-converter; no product with that LO was found, so it is a test
case (`tests/test_core_converters.py`), not a preset.

### "+ QO-100" (OpenHamShack QO-100 NB)

| title | offset | source |
| --- | --- | --- |
| QO-100: LNB 9750 MHz | 9750 MHz, RX only | the standard PLL LNB, 25 MHz × 390; Bullseye LNB datasheet (9750 MHz, 25 MHz TCXO: <https://www.rtl-sdr.com/product/qo-100-bullseye-tcxo-lnb/>); docs/qo100-research.md §3 |
| QO-100: LNB 9750.1 MHz | 9750.1 MHz, RX only | SDR Console's "+ QO-100" pack (screenshot, "QO-100: 9750.1 MHz/8089.5 MHz") |
| QO-100: LNB 9750.225 MHz | 9750.225 MHz, RX only | SDR Console's QO-100 page (<https://www.sdr-radio.com/Console/EsHail2>): its downconverter value |
| QO-100 uplink: 1296 MHz IF (LO 1104) | 1104 MHz, TX only | DXPatrol MK4 upconverter manual (docs/ic9700-research.md, "Upconverters") |
| QO-100 uplink: 432 MHz IF (LO 1968) | 1968 MHz, TX only | F1OPA upconverter (docs/ic9700-research.md) |
| QO-100 uplink: 144 MHz IF (LO 2256) | 2256 MHz, TX only | F1OPA upconverter (docs/ic9700-research.md) |

- The **uplink upconverters are TX only**, so they read as up-converters
  (above, "Use, and which way down means"). Until 07/10/2026 they were
  RX/TX, and the 1296 MHz one showed as a Down-converter in Brian's
  screenshot. NB retypes a copy stored before - `rxtx` true, no `use`,
  every number the preset's - to TX only as it loads; one the operator
  changed is left alone. Nothing it does moves: the TX offset is the same,
  and none of them could ever be the LNB. A config from 0.1.6 or before
  migrates its upconverter LO to TX only too.

- SDR Console's QO-100 entries carry a **TX offset of 8089.5 MHz**. That is
  the transponder's translation (uplink = downlink − 8089.5 MHz), not a
  converter: OpenHamShack QO-100 NB applies it itself, so its LNB presets are receive
  only and a converter must never carry it.
- **27 MHz-crystal LNBs** (the Octagon OSLO) are 9750 MHz LNBs: the PLL
  multiplies the 27 MHz crystal to the same LO (Baltic Lab,
  <https://baltic-lab.com/2023/07/lnb-modification-for-10-ghz-qo-100-satellite-reception/>;
  BATC forum <https://forum.batc.org.uk/viewtopic.php?p=29669>). No entry
  of their own.
- A 25 MHz-design LNB fed **24 MHz** gives 9360 MHz (DJ0ABR's default,
  docs/qo100-research.md §3). That is one program's setup rather than a
  product, so it is not a preset; Add takes it.
- SDR Console's "Warm 9750.000 MHz" entry (in Brian's screenshot) is not
  explained in anything found; it is not copied.

## Where each app uses it

- **NB**: the receive converter (`rxConverter`, the LNB: down, not
  inverted, not TX only - NB's beacon maths are written for that), the
  Pluto's transmit converter (`txConverter`, none by default: the Pluto
  transmits on 2400 MHz itself) and the IC-9700's (`rigTxConverter`,
  required for it); both transmit choices take TX only or RX/TX.
- **HAM**: a converter per band (`bandConverters`); the guard judges the
  on-air frequency, the drive into an RX/TX or TX-only converter is held
  under its most drive, and a band with a TX-only one is received
  directly. DESIGN-HAM.md §5.6 has the as-built notes.

## The drive limit (HAM)

`drive_cap(converter, device_full_w)` is the drive (an amplitude, 0..1)
at which the radio's full output meets the converter's most drive. It is
**0** - nothing - when either number is missing (no most drive; an output
that is zero, unknown or not a number), and 1 only with no converter.
OpenHamShack Radio works it out in one place (`Radio._drive_limit`) and uses it
for the slider's ceiling, the transmit guard and the device:

- it is the **transmit** dial's band and converter (split, XIT, the
  repeater shift), never the receive dial's;
- the full output is the higher of the device's own figure at the IF and
  the band's entered `devW`, so a measurement can only make it stricter;
  with neither known, transmitting through the converter is refused;
- the guard judges it at key-up for the request being keyed, again once
  the over's converter is picked and as the device keys, and again while
  keyed whenever drive, tuneDrive, the power chain or the converters
  change;
- every drive given to a keyed device is clamped to it, whatever the
  state says.

These came out of a safety review of the first version (07/10/2026), which
took the limit from the receive dial, ignored `devW`, read no limit into a
missing number and did not re-judge a waiting over when Settings changed
its converter. `tests/test_ham_xvtr_safety.py` reproduces each one.
