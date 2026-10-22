"""Converters: transverters, LNBs, up- and down-converters between the
radio and the air, as a list of named definitions both apps share.

Modelled on SDR Console's Converter Definitions window (Brian, 07/10/2026),
because that is the vocabulary operators already have: each definition
has a title, a type (down or up), what it is used for - receive only,
transmit only, or both (RX/TX) - and an RX and a TX offset in Hz. OpenHamShack
adds two fields SDR Console lacks: whether the converter **inverts** the
spectrum (a high-side local oscillator) and, for one that transmits, the
**most drive** its input takes (a transverter that wants 0 dBm is
destroyed in a second by a radio's 5 W - docs/ham/DESIGN-HAM.md section 6,
rule 8).

The maths, with `air` the on-air frequency the dial shows and `radio` the
frequency the SDR itself is tuned to:

    down, not inverted:  radio = air - offset      the radio sits below the air (a 23 cm transverter
                                                    on a 144 MHz IF: 1296.2 -> 144.2 with 1152 MHz)
    up, not inverted:    radio = air + offset      the radio sits above (an HF upconverter: 14.2 MHz
                                                    -> 164.2 with 150 MHz)
    inverted (either):   radio = offset - air      a high-side LO: the spectrum is mirrored, USB comes
                                                    out as LSB and the knob runs backwards

The stored type says where the radio sits, below the air (down) or above
it (up), and its name is the receive direction's, as in SDR Console: an
LNB or a transverter is a down-converter because it brings the air down
to the radio. A converter that only transmits is named by what it does on
transmit instead (`kind()`), so the QO-100 uplink upconverter - the radio
at 1296 MHz, below 2400 on air: type down - reads as the up-converter it
is. Only the name follows the use; the formula below is the type's.

A mixer produces only LO + f and |LO - f|. The two non-inverted products
are the two types; the inverted product is LO - f whichever type, and the
type then only says on which side of the air frequency the radio ends up
(an inverting down-converter has offset < 2 x air, an inverting
up-converter more). So the type of an inverted converter is a description
`check()` holds it to, not a different formula.

`rx_offset` serves receive and `tx_offset` transmit, as in SDR Console: a
transverter has the same LO both ways, but nothing obliges a station's
receive and transmit paths to share one.

No Qt and no app here: the apps store the list (an ordered setting,
`converters`, validated by `clean_list`), say which definition is in use
where, and apply `radio()` / `air()` at their device boundary. The built-in
preset packs are at the end, every value sourced in docs/converters.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .i18n.text import _

DOWN, UP = "down", "up"
TYPES = (DOWN, UP)
TYPE_NAMES = {DOWN: "Down", UP: "Up"}
# What a definition is used for. "tx" came on 07/10/2026 for Ray's
# station: an IC-9700 transmitting through an uplink upconverter and an
# SDR receiving, so the upconverter is never in a receive path. Up to then
# this was a bool, `rxtx` (false: receive only), which from_dict still reads.
RX, TX, RXTX = "rx", "tx", "rxtx"
USES = (RX, TX, RXTX)
USE_NAMES = {RX: "RX only", TX: "TX only", RXTX: "RX/TX"}
MAX_CONVERTERS = 100
MAX_TITLE = 60
MAX_OFFSET = 300e9          # Hz: past every amateur band anyone converts to
DRIVE_RANGE = (-60.0, 50.0)  # dBm: what a "most drive" may say (50 dBm = 100 W)

# A mode as it leaves an inverting converter: the radio's USB is LSB on
# air, its CW the reverse sideband (ohsnb/extrig.py has used this since
# the IC-9700 work, for a high-side upconverter).
_INVERT = {"usb": "lsb", "lsb": "usb", "cw": "cw-r", "cw-r": "cw", "rtty": "rtty-r", "rtty-r": "rtty"}


@dataclass(frozen=True)
class Converter:
    title: str
    type: str = DOWN
    use: str = RX                      # RX, TX or RXTX
    rx_offset: float = 0.0             # Hz (a TX-only one carries its TX offset here: it is never read)
    tx_offset: float = 0.0             # Hz
    inverted: bool = False             # high-side LO
    max_drive_dbm: float | None = None  # the most drive its input takes; None: not given

    def __post_init__(self):
        # A bool here is code written for the old `rxtx` field; taking True
        # as some use would be a guess, and a transmit path rests on it.
        if self.use not in USES:
            raise ValueError(_("{title}: use must be one of {uses}, not {use}").format(
                title=self.title, uses=", ".join(USES), use=repr(self.use)))

    @property
    def receives(self) -> bool:
        return self.use != TX

    @property
    def transmits(self) -> bool:
        return self.use != RX

    def kind(self) -> str:
        """DOWN or UP as the hardware is called: the type, except that a
        transmit-only converter is named by its transmit direction, in which
        a radio below the air is converted up to it (the module docstring)."""
        if self.use == TX:
            return UP if self.type == DOWN else DOWN
        return self.type

    def kind_name(self) -> str:
        return "an up-converter" if self.kind() == UP else "a down-converter"

    # ------------------------------------------------------------ the maths
    def offset(self, tx: bool = False) -> float:
        return self.tx_offset if tx else self.rx_offset

    def radio(self, air: float, tx: bool = False) -> float:
        """The frequency the radio must be on for `air` on the air."""
        off = self.offset(tx)
        if self.inverted:
            return off - air
        return air - off if self.type == DOWN else air + off

    def air(self, radio: float, tx: bool = False) -> float:
        """The on-air frequency of `radio` through this converter."""
        off = self.offset(tx)
        if self.inverted:
            return off - radio
        return radio + off if self.type == DOWN else radio - off

    def radio_range(self, lo: float, hi: float, tx: bool = False) -> tuple[float, float]:
        """The radio's frequencies for the air range lo..hi, low to high
        (an inverting converter swaps the ends)."""
        a, b = self.radio(lo, tx), self.radio(hi, tx)
        return (a, b) if a <= b else (b, a)

    def air_range(self, lo: float, hi: float, tx: bool = False) -> tuple[float, float]:
        a, b = self.air(lo, tx), self.air(hi, tx)
        return (a, b) if a <= b else (b, a)

    def air_mode(self, radio_mode: str) -> str:
        """The radio's mode as it is heard on the air (and the reverse: the
        mapping is its own inverse)."""
        return _INVERT.get(radio_mode, radio_mode) if self.inverted else radio_mode

    radio_mode = air_mode

    def check(self, lo: float, hi: float, tx: bool = False) -> str:
        """'' if the air range lo..hi comes out at positive radio
        frequencies on the side the type says; else the sentence."""
        r_lo, r_hi = self.radio_range(lo, hi, tx)
        if r_lo <= 0:
            return (f"{self.title}: {span_mhz(lo, hi)} MHz on air would need the radio at "
                    f"{r_lo / 1e6:.3f} MHz, which is not a frequency")
        below = r_hi < lo
        above = r_lo > hi
        # Said with the name the form shows (kind_name): for a TX-only one
        # that is the transmit direction's, so "below" goes with "up".
        if self.type == DOWN and not below:
            return f"{self.title}: as {self.kind_name()} it must have the radio below the air frequency"
        if self.type == UP and not above:
            return f"{self.title}: as {self.kind_name()} it must have the radio above the air frequency"
        return ""

    def example(self, lo: float, hi: float, tx: bool = False) -> str:
        """'144-146 MHz on air appears at 28-30 MHz on the radio': the
        edit form's example line."""
        a, b = self.radio(lo, tx), self.radio(hi, tx)
        where = "appears at" if not tx else "is sent from"
        tail = " (inverted: the ends swap, USB becomes LSB)" if self.inverted else ""
        return f"{span_mhz(lo, hi)} MHz on air {where} {span_mhz(a, b)} MHz on the radio{tail}"

    # ------------------------------------------------------------ storage
    def to_dict(self) -> dict:
        # `rxtx` is no longer written. A release from before `use` reads a
        # missing rxtx as receive only, so a downgraded copy refuses to
        # transmit through anything until it is set again, rather than
        # guessing; rxOffset stays, because those releases require it.
        return {"title": self.title, "type": self.type, "use": self.use, "rxOffset": self.rx_offset,
                "txOffset": self.tx_offset, "inverted": self.inverted, "maxDriveDbm": self.max_drive_dbm}

    @classmethod
    def from_dict(cls, d: dict) -> "Converter":
        """A stored definition, checked field by field; ValueError with a
        sentence naming the field otherwise. Missing optional fields take
        their defaults (a hand-written entry needs only title, type and
        rxOffset); a missing txOffset is the rxOffset, as a transverter's is.
        A TX-only entry needs txOffset instead, and its rxOffset is set to
        it: nothing receives through it, so no RX offset can matter, and a
        stray number that nothing should read is one fewer to be read.

        `use` is "rx", "tx" or "rxtx". A definition stored before 07/10/2026
        has `rxtx` instead: true is "rxtx", false (or missing) "rx" - the
        same converter as before. With both, `use` wins: it is the newer
        key, and only a hand edit can have written both."""
        if not isinstance(d, dict):
            raise ValueError(_("A converter must be a set of fields"))
        title = d.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE or "\n" in title:
            raise ValueError(_("A converter needs a title of 1-{most} characters on one line").format(most=MAX_TITLE))
        title = title.strip()
        typ = d.get("type", DOWN)
        if typ not in TYPES:
            raise ValueError(_("{title}: type must be down or up").format(title=title))
        if "use" in d:
            use = d["use"]
            if use not in USES:
                raise ValueError(_("{title}: use must be rx, tx or rxtx").format(title=title))
        else:
            old = d.get("rxtx", False)
            if not isinstance(old, bool):
                raise ValueError(_("{title}: rxtx must be true or false").format(title=title))
            use = RXTX if old else RX
        inverted = d.get("inverted", False)
        if not isinstance(inverted, bool):
            raise ValueError(_("{title}: inverted must be true or false").format(title=title))
        if use == TX:
            tx = _offset(title, "TX offset", d.get("txOffset"))
            rx = tx
        else:
            rx = _offset(title, "RX offset", d.get("rxOffset"))
            tx = _offset(title, "TX offset", d.get("txOffset", rx))
        drive = d.get("maxDriveDbm")
        if drive is not None:
            if isinstance(drive, bool) or not isinstance(drive, (int, float)) or not math.isfinite(float(drive)):
                raise ValueError(_("{title}: the most drive must be a number of dBm").format(title=title))
            if not DRIVE_RANGE[0] <= float(drive) <= DRIVE_RANGE[1]:
                raise ValueError(_("{title}: the most drive must be between {lo:g} and {hi:g} dBm").format(
                    title=title, lo=DRIVE_RANGE[0], hi=DRIVE_RANGE[1]))
            drive = float(drive)
        return cls(title, typ, use, rx, tx, inverted, drive)

    def copy_as(self, title: str) -> "Converter":
        return replace(self, title=title)


def _offset(title: str, name: str, v) -> float:
    # `name` is "TX offset" or "RX offset"; each has its own whole
    # sentences, because a translation cannot slot a translated noun into
    # another language's word order.
    tx = name == "TX offset"
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        msg = _("{title}: TX offset must be a number of Hz") if tx else _("{title}: RX offset must be a number of Hz")
        raise ValueError(msg.format(title=title))
    v = float(v)
    if not 0 < v <= MAX_OFFSET:
        msg = (_("{title}: TX offset must be above 0 and at most {most:g} GHz") if tx
               else _("{title}: RX offset must be above 0 and at most {most:g} GHz"))
        raise ValueError(msg.format(title=title, most=MAX_OFFSET / 1e9))
    return v


def span_mhz(a: float, b: float) -> str:
    """'144-146', '10489.5-10490', '30-28' (an inverted range keeps its order)."""
    return f"{_mhz(a)}-{_mhz(b)}"


def _mhz(f: float) -> str:
    s = f"{f / 1e6:.6f}".rstrip("0").rstrip(".")
    return s or "0"


# ------------------------------------------------------------------ the list
def clean_list(value: list) -> list[dict]:
    """Validate a stored `converters` value: an ordered list of definitions
    with distinct titles (a band or a path names its converter by title).
    ValueError with a sentence on anything wrong - refused, never repaired,
    because a transmit drive limit is in here and the guard trusts it
    (the same contract as ohsradio/power.py's chain)."""
    if not isinstance(value, list):
        raise ValueError(_("converters must be a list"))
    if len(value) > MAX_CONVERTERS:
        raise ValueError(_("At most {most} converters").format(most=MAX_CONVERTERS))
    out, seen = [], set()
    for d in value:
        c = Converter.from_dict(d)
        key = c.title.casefold()
        if key in seen:
            raise ValueError(_("Two converters are called {title}: titles must differ").format(title=repr(c.title)))
        seen.add(key)
        out.append(c.to_dict())
    return out


def parse(value: list) -> list[Converter]:
    return [Converter.from_dict(d) for d in (value or [])]


def find(value: list, title: str) -> Converter | None:
    """The definition called `title` in a stored list ('' or missing: None)."""
    if not title:
        return None
    for d in value or []:
        if isinstance(d, dict) and str(d.get("title", "")).strip().casefold() == title.strip().casefold():
            return Converter.from_dict(d)
    return None


def unique_title(value: list, base: str) -> str:
    """`base`, or `base (2)`, `base (3)`... whichever is free: what Copy
    and a preset pack use, so neither ever overwrites a definition."""
    taken = {str(d.get("title", "")).casefold() for d in value or [] if isinstance(d, dict)}
    if base.casefold() not in taken:
        return base
    n = 2
    while f"{base} ({n})".casefold() in taken:
        n += 1
    return f"{base} ({n})"


def add_pack(value: list, pack: list[Converter]) -> list[dict]:
    """The list with a preset pack appended. A preset already there under
    its own title is not added again (pressing the button twice does
    nothing the second time); the operator's own entries are never
    touched."""
    out = [dict(d) for d in value or []]
    have = {str(d.get("title", "")).casefold() for d in out}
    for c in pack:
        if c.title.casefold() not in have:
            out.append(c.to_dict())
            have.add(c.title.casefold())
    return out


def drive_cap(c: Converter | None, device_full_w: float) -> float:
    """The most drive (0..1 of the device's full output amplitude) that
    keeps the converter's input at or under its maximum: 1.0 with no
    converter, or when the device cannot reach the maximum anyway. Drive is
    an amplitude, so power goes as its square.

    0.0 - nothing - when either number is missing: a converter with no most
    drive, or a device whose full output is zero, unknown or not a number.
    Until 07/10/2026 both gave 1.0, no limit, which is the one answer that
    can destroy the transverter; a caller that wants to transmit has to
    say why it cannot (ohsradio/radio.py _drive_limit)."""
    if c is None:
        return 1.0
    if c.max_drive_dbm is None or not (math.isfinite(device_full_w) and device_full_w > 0):
        return 0.0
    allowed_w = 10 ** (c.max_drive_dbm / 10) / 1000.0
    return min(1.0, math.sqrt(allowed_w / device_full_w))


# ------------------------------------------------------------------ presets
# Every value below is a published product LO or a convention printed by
# the program Brian took the idea from; docs/converters.md gives the
# source of each. Titles follow SDR Console's where it has the entry, so
# an operator moving across recognises them.
def _x(title, lo_mhz, typ=DOWN, use=RXTX, drive=None):
    off = lo_mhz * 1e6
    return Converter(title, typ, use, off, off, False, drive)


# Transverters on the two IFs most are sold for (28 MHz for an HF radio,
# 144 MHz for a 2 m one), and the HF upconverters that put 0-30 MHz above
# a VHF-only SDR. No drive limit is preset: it is the one number that has
# to come from the operator's own transverter's manual, and a preset value
# would look as if it had. All low-side (LO = RF - IF, not inverted), as
# every product looked up was. Combinations whose LO could not be read in
# a manufacturer's or SDR Console's own text (4 m on 28 MHz, 432 or 2320
# on 144, 10 GHz) are left out rather than worked out: Add takes them in
# a few seconds, with the number from the operator's own manual.
VHF_UHF_SHF = [
    _x("50 MHz (28 MHz IF)", 22),             # Elecraft XV50
    _x("144 MHz (28 MHz IF)", 116),           # Elecraft XV144
    _x("432 MHz (28 MHz IF)", 404),           # Down East Microwave L432-28
    _x("1296 MHz (28 MHz IF)", 1268),         # SDR Console's pack; Kuhne TR1296H28
    _x("1296 MHz (144 MHz IF)", 1152),        # SDR Console's pack
    _x("2304 MHz (28 MHz IF)", 2276),         # SDR Console's pack
    _x("2304 MHz (144 MHz IF)", 2160),        # SDR Console's pack
    _x("3400 MHz (144 MHz IF)", 3256),        # Down East Microwave MINI3400
    _x("5760 MHz (144 MHz IF)", 5616),        # Down East Microwave 5760-144
    _x("HF upconverter (125 MHz)", 125, UP, use=RX),    # NooElec Ham It Up
    _x("HF upconverter (120 MHz)", 120, UP, use=RX),    # Airspy SpyVerter
]

# QO-100's narrowband downlink through an LNB, and the 2.4 GHz uplink from
# a radio's IF. The uplink upconverters are TX only (RX/TX up to
# 07/10/2026, which named them "Down-converter": they only ever transmit,
# NB never receives through them, and as TX only they read as the
# up-converters they are; ohsnb/converters.py retypes a stored copy).
# The LNBs are receive only: SDR Console pairs each with a TX
# offset of 8089.5 MHz, but that is the transponder's own translation
# (uplink = downlink - 8089.5 MHz), which QO-100 NB applies itself - a
# converter carrying it would apply it twice. A 27 MHz-crystal LNB (the
# Octagon OSLO) is a 9750 MHz LNB too: its PLL multiplies to the same LO,
# so it needs no entry of its own.
QO100 = [
    _x("QO-100: LNB 9750 MHz", 9750, use=RX),            # 25 MHz x 390; Bullseye datasheet
    _x("QO-100: LNB 9750.1 MHz", 9750.1, use=RX),        # SDR Console's pack
    _x("QO-100: LNB 9750.225 MHz", 9750.225, use=RX),    # SDR Console's QO-100 page
    _x("QO-100 uplink: 1296 MHz IF (LO 1104)", 1104, use=TX),    # DXPatrol MK4 (DIP switch S1)
    _x("QO-100 uplink: 432 MHz IF (LO 1968)", 1968, use=TX),     # F1OPA; DXPatrol MK4 too
    _x("QO-100 uplink: 144 MHz IF (LO 2256)", 2256, use=TX),     # F1OPA; DXPatrol MK4 too
]

PACKS = {"vhf": ("VHF/UHF/SHF", VHF_UHF_SHF), "qo100": ("QO-100", QO100)}
