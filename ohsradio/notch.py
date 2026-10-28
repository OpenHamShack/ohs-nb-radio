"""The SDRplay RSP's broadcast notch filters: when they are in (Brian,
24/10/2026).

Why: Brian's station is about 8 km line of sight from the Ayr DAB
transmitter (block 11B, 218.640 MHz). On the RSPdx's Antenna A that
multiplex overloads the front end even with the receiver tuned somewhere
else entirely - 2 m included - because nothing ahead of the LNA stops it.
SDRplay fit two switchable notches for exactly this, a DAB (Band III)
notch and a broadcast notch, and until now Radio left both at the API's
default, off. These two settings switch them:

- **`dabNotch`** (shack_sdr's `dab_notch`) auto is **out by default
  everywhere**, and goes in only when the RSP reports overload while its
  span is clear of 150-240 MHz (`DAB_STOPBAND`) - `DabAuto` below. That
  is the notch's own stopband (>30 dB over 160-230 MHz on an RSPdx, >20
  dB over 155-235) with a margin for the skirt, not Band III alone: until
  28/10/2026 the guard was 174-240 MHz, so overload seen while listening
  to marine VHF (156-162 MHz) or AIS (161.975/162.025 MHz) could switch in
  a notch 30 dB deep across the very signal being received (found by the
  AIS work).
  Measured on ohs-box (24/10/2026, Store Radio beta.7, RSPdx, Antenna A,
  145.300 MHz FM, rxGain 40, back-to-back minutes): with the DAB notch in
  the repeater was about 4 dB weaker (insertion loss) and about 2.5 dB
  lower over the noise floor, and there were no overloads with it in or
  out - so on 2 m it cost 2.5 dB and bought nothing. (beta.7's rule put it
  in everywhere outside Band III.) Within 150-240 MHz, or while a DAB or
  AIS session holds the receiver, it is always out.
- **`rfNotch`** (shack_sdr's `rf_notch`) is in only while the whole span
  lies below 60 MHz (`RF_AUTO_TOP`), and even there out while it touches
  the LW or MW broadcast bands (`AM_BANDS`). The one switch is both an FM
  and an MW notch (below): on HF and LF the MW part helps and the FM part
  costs nothing, but above 60 MHz - the FM band itself, 2 m, 70 cm, Band
  III - it is out, because on 2 m it costs at least 4 dB (below) and Radio
  is mostly a 2 m receiver. A station near a strong FM transmitter sets
  `on`. (24/10/2026, before Store Radio beta.7: the first rule kept it in
  everywhere outside the FM and AM broadcast bands, 2 m included.)

`on` and `off` hold a notch whatever is tuned: for comparing, or for a
station whose neighbour is somewhere the rule does not expect.

**What the switches cover** (checked 24/10/2026). SDRplay's API
Specification 3.15 says nothing about it - every field is just "default:
0" - so this is from the datasheets:

- RSPdx (datasheet V1.3, "Specifications"): `rfNotchEnable` is the FM
  *and* MW notch, one switch - FM >30 dB 77-115 MHz, >50 dB 85-107 MHz;
  MW >30 dB 500-1530 kHz, >15 dB 400-1650 kHz. `rfDabNotchEnable` is
  >30 dB 160-230 MHz, >20 dB 155-235 MHz. The same datasheet gives the
  FM notch >4 dB at 144-148 MHz: **in, it costs at least 4 dB on 2 m**,
  which is why automatic takes it out above 60 MHz.
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
scan's hops), whenever either setting changes, and whenever DabAuto's
verdict does (Radio._notch_tick asks for a reconfigure). A reopen (the radio
lost and found again) takes what was last applied, because the device
hands it to the source it constructs (ohscore/devices/sdrsource.py).
"""
from __future__ import annotations

from ohsradio.i18n import _

from . import bcastgain

CHOICES = ("auto", "on", "off")

# dabNotch auto never puts the notch in while the span touches this: the
# RSPdx DAB notch's stopband (>20 dB 155-235 MHz) plus a margin for the
# skirt (module docstring). It covers Band III (174-240), marine VHF and
# AIS.
DAB_STOPBAND = (150_000_000.0, 240_000_000.0)
FM_BROADCAST = (87_500_000.0, 108_000_000.0)
# rfNotch auto: in only below this (module docstring). 6 m (50-52 MHz) is
# under it and far enough from the FM notch's 77 MHz lower edge; 4 m (70
# MHz) is over it, so its edge is never in question.
RF_AUTO_TOP = 60_000_000.0
# LW 148.5-283.5 kHz (ITU Region 1); MW 526.5 kHz to 1705 kHz, Region 2's
# top edge rather than Region 1's 1606.5, so a station anywhere is covered.
# 160 m starts at 1810 kHz, outside both.
AM_BANDS = ((148_500.0, 283_500.0), (526_500.0, 1_705_000.0))


def _touches(lo: float, hi: float, band: tuple[float, float]) -> bool:
    return lo < band[1] and hi > band[0]


def in_stopband(lo: float, hi: float) -> bool:
    return _touches(lo, hi, DAB_STOPBAND)


def auto_dab(lo: float, hi: float, dab_held: bool, overload_in: bool) -> bool:
    """Whether `auto` puts the DAB notch in for a span lo..hi Hz, given
    DabAuto's verdict (`overload_in`)."""
    return overload_in and not dab_held and not in_stopband(lo, hi)


def auto_rf(lo: float, hi: float) -> bool:
    """Whether `auto` puts the broadcast notch in for a span lo..hi Hz."""
    return hi <= RF_AUTO_TOP and not any(_touches(lo, hi, b) for b in AM_BANDS)


def _pick(setting: str, auto: bool) -> bool:
    return {"on": True, "off": False}.get(str(setting), auto)


def wanted(dab_setting: str, rf_setting: str, lo: float, hi: float, dab_held: bool = False,
           overload_in: bool = False) -> dict[str, bool]:
    """The switches to set, by shack_sdr's names, for the two settings and
    the device's span lo..hi Hz (`overload_in`: DabAuto's verdict)."""
    return {"dab_notch": _pick(dab_setting, auto_dab(lo, hi, dab_held, overload_in)),
            "rf_notch": _pick(rf_setting, auto_rf(lo, hi))}


# DabAuto (seconds). The debounce is broadcast gain's for wide FM
# (bcastgain.py WINDOW_S, DEBOUNCE): the SDRplay overload report flickers
# (Brian's Band III sweep saw it true on blocks whose FIBs were clean), so
# one report is not enough - it must be there in DEBOUNCE one-second
# windows running.
WINDOW_S = bcastgain.WINDOW_S
DEBOUNCE = bcastgain.DEBOUNCE
# In, it comes out after this long with no overload at all...
HOLD_S = 300.0
# ...but put back in within MEMORY_S of coming out, the next hold is twice
# as long (up to HOLD_MAX_S): a neighbour that keeps coming back keeps the
# notch in rather than flapping it every five minutes. Out for MEMORY_S,
# the hold is HOLD_S again.
MEMORY_S = 3600.0
HOLD_MAX_S = 3600.0


class DabAuto:
    """dabNotch auto's verdict (module docstring), driven ten times a
    second from Radio's supervisor tick with the device's span and whether
    it reported a new overload since the last look. `inn` is read on the
    receive thread (one bool, assigned whole)."""

    def __init__(self):
        self.inn = False
        self.streak = 0
        self._win: dict | None = None
        self.last_over: float | None = None
        self.out_at: float | None = None
        self.hold = HOLD_S
        self.why = "default"
        self.at_hz: float | None = None

    def tick(self, now: float, over: bool, lo: float, hi: float, dab_held) -> bool:
        """True when the verdict changed. `dab_held`: what holds the
        receiver where the notch must stay out - "dab", "ais" (Radio
        _dab_held), True for DAB - or nothing."""
        if dab_held or in_stopband(lo, hi):
            # Never in here, and what was seen elsewhere does not carry in.
            self._win, self.streak = None, 0
            why = (dab_held if isinstance(dab_held, str) else "dab") if dab_held else "stopband"
            if self.inn:
                self.inn, self.out_at, self.why = False, now, why
                return True
            if self.why in ("default", "clear", "stopband", "dab", "ais"):
                self.why = why
            return False
        if self.why in ("stopband", "dab", "ais"):
            self.why = "default"
        if self._win is None:
            self._win = {"t": now, "over": False}
        w = self._win
        w["over"] = w["over"] or bool(over)
        if now - w["t"] < WINDOW_S:
            return False
        self._win = None
        if w["over"]:
            self.last_over = now
            if self.inn:
                return False
            self.streak += 1
            if self.streak < DEBOUNCE:
                return False
            self.streak = 0
            if self.out_at is not None and now - self.out_at < MEMORY_S:
                self.hold = min(self.hold * 2, HOLD_MAX_S)
            self.inn, self.why, self.at_hz = True, "overload", (lo + hi) / 2
            return True
        self.streak = 0
        if self.inn and now - self.last_over >= self.hold:
            self.inn, self.out_at, self.why = False, now, "clear"
            return True
        if not self.inn and self.out_at is not None and now - self.out_at >= MEMORY_S:
            self.hold = HOLD_S
        return False

    def text(self) -> str:
        if self.why == "overload":
            return _("in: overload seen at {mhz} MHz").format(mhz=f"{(self.at_hz or 0) / 1e6:.3f}")
        if self.why == "clear":
            return _("out: no overload for {minutes:g} min").format(minutes=self.hold / 60)
        if self.why == "stopband":
            return _("out: tuned within 150-240 MHz, where this notch would cut what you hear")
        if self.why == "dab":
            return _("out: a DAB station is playing")
        if self.why == "ais":
            return _("out: AIS is listening at 162 MHz, inside this notch's stopband")
        return _("out: no overload seen")
