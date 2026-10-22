"""Transverters and converters per band: OpenHamShack Radio's use of the shared
converter list (ohscore/converters.py; docs/ham/DESIGN-HAM.md section 5.6).

A band is worked either directly (the radio tunes it) or through one
converter from the list, chosen per band in Settings › Converters
(`bandConverters`, {band: title}). Through one, the dial and everything
judged by it stay on the air: the licence and band-plan guard, the band
bar, the log, the memories - only the device is told the converter's IF
(`Converter.radio`), and an inverting one has the engine mirror the IQ at
the device (Engine.rx_invert / tx_invert). Uses the design names: a Pluto
on a 2 m IF for 23 cm and up, an HL2 on 28 MHz for 2 m, 4 m or 6 m, an HF
upconverter in front of a receive-only SDR.

Transmitting through one is the one place in the program where a wrong
number destroys hardware in a second (DESIGN-HAM section 6, rule 8): a
transverter that wants 0 dBm, fed a radio's 5 W. So:

- only an RX/TX or TX-only definition transmits, and only once it gives its **most
  drive**: a band cannot be set to transmit through one without it, and a
  stored one without it (a hand-edited file) refuses to key;
- the drive slider's ceiling (`maxDrive`) is the lower of the band's own
  and the drive at which the device's full output (the higher of its own
  figure and the band's measured devW) meets the transmit dial's
  converter's most drive; an unknown output refuses rather than meaning
  no limit, and every drive a keyed device is given is clamped to it
  (ohsradio/radio.py `_drive_limit`, `_drive_device`; docs/converters.md);
- an HL2 whose PA is on (saved or running) refuses a converter that wants 0 dBm or less: the
  design's "forces the PA off", done as a refusal with the sentence, since
  the PA setting needs a restart and must stay the operator's to change;
- a TX-only converter is in the band's transmit path only: the band is
  received directly (`rx_for_band`), never through it. Every transmit
  check treats it exactly as an RX/TX one - the lookups the transmit
  side makes (`for_band`, Radio._conv_at) include it by default, so a
  path that forgets to ask still meets its drive cap;
- a band set to a converter that is not in the list refuses to transmit
  rather than falling back to direct: the radio's output is wired to the
  transverter's IF input, and direct would put the band's own frequency,
  at the radio's own power, into it.
"""
from __future__ import annotations

from ohscore import converters as cv

from ohsradio.i18n import _

HL2_PA_OFF_AT_DBM = 0.0     # design rule 8: a converter wanting this or less needs the HL2's PA off


def clean_band_converters(value: dict) -> dict:
    """Validate a stored bandConverters value: {band name: converter title}.
    An unknown band or a title that is not text is refused with the
    sentence; whether the title is in the list is a cross-key matter
    (`check`), judged when Settings saves."""
    from .bands import BY_NAME
    out = {}
    for band, title in value.items():
        if band not in BY_NAME:
            raise ValueError(_("bandConverters: no band called {band}").format(band=repr(band)))
        if not isinstance(title, str) or len(title) > cv.MAX_TITLE or "\n" in title:
            raise ValueError(_("bandConverters {band}: the converter must be named by its title").format(band=band))
        if title.strip():
            out[band] = title.strip()
    return out


def title_for(st: dict, band: str) -> str:
    return (st.get("bandConverters") or {}).get(band, "")


def for_band(st: dict, band: str) -> cv.Converter | None:
    """The converter band `band` is worked through, or None (direct, or a
    title that is not in the list - see `missing`)."""
    return cv.find(st.get("converters"), title_for(st, band))


def rx_for_band(st: dict, band: str) -> cv.Converter | None:
    """The converter band `band` is received through: the band's, unless it
    is TX only, when the band is received directly."""
    c = for_band(st, band)
    return c if c is not None and c.receives else None


def missing(st: dict, band: str) -> str:
    """The sentence if `band` names a converter the list does not have."""
    title = title_for(st, band)
    if title and for_band(st, band) is None:
        return (f"{band} is set to work through {title!r}, which is not in the converter list "
                f"(Settings › Converters)")
    return ""


def deferred(st: dict, b) -> str:
    """A band with no radio here (6 m) is available through a converter."""
    return "" if b.deferred and for_band(st, b.name) is not None else b.deferred


def reach(b, conv: cv.Converter | None, rx_range: tuple[float, float]) -> bool:
    """Whether a radio tuning rx_range reaches any of band `b` (through `conv`)."""
    lo, hi = conv.radio_range(b.lo, b.hi) if conv is not None else (b.lo, b.hi)
    return hi >= rx_range[0] and lo <= rx_range[1]


def tx_problem(st: dict, band: str, device: str, hl2_pa: bool) -> str:
    """Why a transmission on `band` may not go through its converter, or ''."""
    why = missing(st, band)
    if why:
        return why
    c = for_band(st, band)
    if c is None:
        return ""
    if not c.transmits:
        return f"{c.title} is receive only: {band} can be received through it, not transmitted on"
    if c.max_drive_dbm is None:
        return (f"Enter {c.title}'s most drive (Settings › Converters) before transmitting through it: it is "
                f"the number that keeps the radio from destroying the transverter")
    if device == "hl2" and hl2_pa and c.max_drive_dbm <= HL2_PA_OFF_AT_DBM:
        return (f"{c.title} takes at most {c.max_drive_dbm:g} dBm: turn the Hermes-Lite 2's power amplifier "
                f"off (Settings › Radio) before transmitting through it - even its low-level output is 17 dBm")
    return ""


def check(st: dict) -> None:
    """Settings' save (through Radio._adjust_set): every band's converter is
    in the list, puts that band at a positive frequency on the right side,
    and - if it transmits - gives its most drive."""
    from .bands import BY_NAME
    for band, title in (st.get("bandConverters") or {}).items():
        why = missing(st, band)
        if why:
            raise ValueError(why)
        c = for_band(st, band)
        b = BY_NAME[band]
        why = (c.check(b.lo, b.hi) if c.receives else "") or (c.check(b.lo, b.hi, tx=True) if c.transmits else "")
        if why:
            raise ValueError(f"{band}: {why}")
        if c.transmits and c.max_drive_dbm is None:
            raise ValueError(_("{converter} transmits ({use}), so it needs its most drive in dBm, from "
                               "its manual, before {band} can use it: it is the one number here that, wrong, "
                               "destroys hardware").format(converter=c.title, use=cv.USE_NAMES[c.use], band=band))
