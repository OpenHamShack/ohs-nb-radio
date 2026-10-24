"""The SDRplay RSP's broadcast notch filters: when they are in (Brian,
24/10/2026).

Why: Brian's station is about 8 km line of sight from the Ayr DAB
transmitter (block 11B, 218.640 MHz). On the RSPdx's Antenna A that
multiplex overloads the front end even with the receiver tuned somewhere
else entirely - 2 m included - because nothing ahead of the LNA stops it.
SDRplay fit two switchable notches for exactly this, a DAB (Band III)
notch and a broadcast notch, and until now Radio left both at the API's
default, off. These two settings switch them, and `auto` puts each in
wherever it cannot be in the way:

- **`dabNotch`** (shack_sdr's `dab_notch`) is in unless the receiver's
  span touches Band III, 174-240 MHz (`BAND_III`), and out while a DAB
  session holds the receiver - which centres it on a block, so in Band
  III anyway; the hold is checked as well so a DAB session never depends
  on a centring rule elsewhere.
- **`rfNotch`** (shack_sdr's `rf_notch`) is in unless the span touches
  the FM broadcast band, 87.5-108 MHz, or the LW or MW AM broadcast bands
  (`AM_BANDS`): the one switch is both an FM and an MW notch (below).

`on` and `off` hold a notch whatever is tuned: for comparing, or for a
station whose neighbour is somewhere the rule does not expect.

**What the switches cover** (checked 24/10/2026). SDRplay's API
Specification 3.15 says nothing about it - every field is just "default:
0" - so this is from the datasheets:

- RSPdx (datasheet V1.3, "Specifications"): `rfNotchEnable` is the FM
  *and* MW notch, one switch - FM >30 dB 77-115 MHz, >50 dB 85-107 MHz;
  MW >30 dB 500-1530 kHz, >15 dB 400-1650 kHz. `rfDabNotchEnable` is
  >30 dB 160-230 MHz, >20 dB 155-235 MHz. The same datasheet gives the
  FM notch >4 dB at 144-148 MHz: **in, it costs at least 4 dB on 2 m**.
  Automatic still puts it in there, as asked (Brian's rule); `rfNotch
  off` is the setting for a 2 m station with no FM broadcaster nearby.
- RSP1A and RSP1B (which the API drives through the RSP1A's fields):
  the same pair, "AM/FM" and DAB; FM >50 dB 85-100 MHz, MW >30 dB
  660-1550 kHz, DAB >30 dB 165-230 MHz (RSP1B datasheet).
- RSP2: "MW/FM" only (FM >60 dB 80-100 MHz, MW >30 dB 680-1550 kHz);
  no DAB notch, and the API has no field for one.
- RSPduo: on its two 50 ohm inputs the same FM+MW and DAB pair as the
  RSPdx; on Tuner 1's Hi-Z input `rf_notch` is that port's own MW-only
  notch (`tuner1AmNotchEnable`, >30 dB 560-1470 kHz: shack_sdr switches
  whichever the selected input has), and the DAB notch does nothing there.

"The span" is what the device itself is tuned to, its local oscillator
plus and minus half the sample rate (`rx_if`, so through a transverter it
is the IF the RSP sees, not the dial on the air): a notch is a filter on
the RSP's input, so it is the RSP's own frequency that matters. Half the
sample rate rather than the tuner's 1.536 MHz bandwidth, so a station near
the edge of the waterfall is still treated as tuned.

**Where they apply** is only an RSP whose model has the switch (shack_sdr's
`SdrplaySource._option_targets`, from SoapySDRPlay3's own mapping): the
RSPdx and RSPdx R2, RSP1A and RSP1B, and the RSPduo have both; the RSP2
has the broadcast notch and no DAB notch; the original RSP1 has neither.
On any other radio (Pluto, HL2, RTL-SDR, the simulator) the settings do
nothing at all - they stay in Settings, as `sdrplayLna` does, and the
device is never asked. `deviceStatus.options` shows each switch the open
RSP has, as SDRplay's API holds it.

Applied live, between two reads on the receive thread, with one
`sdrplay_api_Update` per switch and no reopen (ohsradio/radio.py
`_apply_notches`): whenever the centre moves (a dial change that leaves
the span, a DAB session taking or giving back the receiver, the band
scan's hops) and whenever either setting changes. A reopen (the radio
lost and found again) takes what was last applied, because the device
hands it to the source it constructs (ohscore/devices/sdrsource.py).
"""
from __future__ import annotations

CHOICES = ("auto", "on", "off")

BAND_III = (174_000_000.0, 240_000_000.0)
FM_BROADCAST = (87_500_000.0, 108_000_000.0)
# LW 148.5-283.5 kHz (ITU Region 1); MW 526.5 kHz to 1705 kHz, Region 2's
# top edge rather than Region 1's 1606.5, so a station anywhere is covered.
# 160 m starts at 1810 kHz, outside both.
AM_BANDS = ((148_500.0, 283_500.0), (526_500.0, 1_705_000.0))


def _touches(lo: float, hi: float, band: tuple[float, float]) -> bool:
    return lo < band[1] and hi > band[0]


def auto_dab(lo: float, hi: float, dab_held: bool) -> bool:
    """Whether `auto` puts the DAB notch in for a span lo..hi Hz."""
    return not dab_held and not _touches(lo, hi, BAND_III)


def auto_rf(lo: float, hi: float) -> bool:
    """Whether `auto` puts the broadcast notch in for a span lo..hi Hz."""
    return not any(_touches(lo, hi, b) for b in (FM_BROADCAST, *AM_BANDS))


def _pick(setting: str, auto: bool) -> bool:
    return {"on": True, "off": False}.get(str(setting), auto)


def wanted(dab_setting: str, rf_setting: str, lo: float, hi: float, dab_held: bool = False) -> dict[str, bool]:
    """The switches to set, by shack_sdr's names, for the two settings and
    the device's span lo..hi Hz."""
    return {"dab_notch": _pick(dab_setting, auto_dab(lo, hi, dab_held)),
            "rf_notch": _pick(rf_setting, auto_rf(lo, hi))}
