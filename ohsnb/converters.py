"""QO-100 NB's use of the shared converter list (ohscore/converters.py).

Three places a converter sits on a QO-100 station:

- **receive** (`rxConverter`): the LNB, never a TX-only converter. Required - nothing tunes 10 GHz
  directly - and it replaces the single "LNB local oscillator" setting
  NB had up to 0.1.6 (`lnbLo`): the receiver tunes
  IF = dl - offset + rxCorr exactly as it tuned dl - lnbLo + rxCorr.
  Only a down-converter that does not invert is accepted: beacon lock,
  click-to-lock and the GPS-LNB prediction are all written for an IF
  that rises with the downlink, and no QO-100 LNB in use inverts (a 27
  MHz-crystal LNB is still 9750 MHz; docs/converters.md).
- **transmit with the Pluto** (`txConverter`): usually none - the Pluto
  transmits on 2400 MHz itself. A station whose SDR drives an upconverter
  from a lower IF names it here; the engine then tunes the SDR to the IF
  and, for an inverting one, mirrors what it sends.
- **transmit with the IC-9700** (`rigTxConverter`): the upconverter from
  the radio's band to 2.4 GHz. It replaces `upconverterLo` and
  `upconverterSide` (low-side: down, not inverted; high-side: inverted),
  and like the LO before it has no default: a guessed one would put the
  uplink somewhere else entirely.

The transponder's own 8089.5 MHz is never a converter (NB applies it in
bandplan.ul), which is why the QO-100 LNB presets are receive only.

Each path keeps its own converter so that switching Settings › Transmitter
from the IC-9700 to the Pluto can never send the Pluto's output to the
IC-9700's upconverter frequency, and back.
"""
from __future__ import annotations

import math

from ohscore import converters as cv

from . import bandplan

LNB_DEFAULT = cv.QO100[0]           # "QO-100: LNB 9750 MHz": what lnbLo defaulted to
DEFAULT_LIST = [LNB_DEFAULT.to_dict()]
PLUTO_FULL_DBM = 6.5                # the Pluto's output at 0 dB gain (kittenlabs; docs/qo100-research.md section 4)
SDR_RANGE = (70e6, 6e9)             # what the Pluto family tunes (AD9364 setting); an AD9363 says less when opened


def rx_ok(c: cv.Converter | None) -> str:
    """'' if `c` can be NB's receive converter; else why not."""
    if c is None:
        return "Choose the LNB (Settings › Converters): OpenHamShack QO-100 NB cannot receive 10 GHz without one"
    if not c.receives:
        # Before the range check below, which a TX-only uplink converter
        # fails anyway: the sentence should name the real reason.
        return f"{c.title} is TX only: nothing can be received through it, so it cannot be the LNB"
    if c.inverted or c.type != cv.DOWN:
        return (f"{c.title} cannot be the LNB: OpenHamShack QO-100 NB receives through a down-converter that does not invert "
                f"(every QO-100 LNB is one)")
    lo, hi = c.radio_range(bandplan.DL_LO, bandplan.DL_HI)
    if lo < SDR_RANGE[0] or hi > SDR_RANGE[1]:
        return (f"{c.title} puts the downlink at {cv.span_mhz(lo, hi)} MHz, outside what the SDR tunes "
                f"({SDR_RANGE[0] / 1e6:g}-{SDR_RANGE[1] / 1e6:g} MHz)")
    return ""


def tx_ok(c: cv.Converter | None, title: str, what: str) -> str:
    """'' if a transmit path's converter `title` (resolved to `c`) can be
    used; else why not. `what` names the path for the sentence."""
    if not title:
        return ""
    if c is None:
        return f"The {what} converter {title!r} is not in the list (Settings › Converters)"
    if not c.transmits:
        return (f"{c.title} is receive only: mark it TX only or RX/TX in Settings › Converters to transmit "
                f"through it")
    return c.check(bandplan.UL_LO, bandplan.UL_HI, tx=True)


def rx_converter(cfg: dict) -> cv.Converter | None:
    return cv.find(cfg.get("converters"), cfg.get("rxConverter", ""))


def rx_lo(cfg: dict) -> float:
    """The LNB's LO the receiver works with: the receive converter's RX
    offset (what `lnbLo` was), or the standard 9750 MHz while none can be
    found - a config Settings would refuse, kept receiving rather than
    stopped (the simulator reads this too)."""
    c = rx_converter(cfg)
    return c.rx_offset if c is not None and not rx_ok(c) else LNB_DEFAULT.rx_offset


def tx_converter(cfg: dict) -> cv.Converter | None:
    return cv.find(cfg.get("converters"), cfg.get("txConverter", ""))


def rig_converter(cfg: dict) -> cv.Converter | None:
    return cv.find(cfg.get("converters"), cfg.get("rigTxConverter", ""))


def check(st: dict) -> None:
    """Raise ValueError if the converter choices cannot work (Settings'
    save, through Radio._adjust_set)."""
    why = rx_ok(rx_converter(st))
    if why:
        raise ValueError(why)
    why = tx_ok(tx_converter(st), st.get("txConverter", ""), "Pluto's transmit")
    if not why and tx_converter(st) is not None:
        lo, hi = tx_converter(st).radio_range(bandplan.UL_LO, bandplan.UL_HI, tx=True)
        if lo < SDR_RANGE[0] or hi > SDR_RANGE[1]:
            why = (f"{tx_converter(st).title} needs the SDR to transmit on {cv.span_mhz(lo, hi)} MHz, outside "
                   f"{SDR_RANGE[0] / 1e6:g}-{SDR_RANGE[1] / 1e6:g} MHz")
    if why:
        raise ValueError(why)
    why = tx_ok(rig_converter(st), st.get("rigTxConverter", ""), "IC-9700's")
    if why:
        raise ValueError(why)


def drive_dbm(tx_gain_db: float) -> float:
    """What the Pluto puts into a transmit converter at `tx_gain_db`."""
    return PLUTO_FULL_DBM + tx_gain_db


# ------------------------------------------------------------------ migration
def _title_for(lo: float, base: str, transmits: bool, inverted: bool = False) -> tuple[str, cv.Converter | None]:
    """A preset with exactly this LO and direction, or a new title."""
    for c in cv.QO100:
        if c.tx_offset == lo and c.transmits == transmits and not inverted:
            return c.title, c
    return base, None


def migrate(raw: dict, notes: list[str]) -> dict:
    """lnbLo, upconverterLo and upconverterSide (NB up to 0.1.6) became
    converter definitions and the choice of one (the release after). Applied to
    every input, file or dict, like beaconMode's rename: the old keys'
    presence is the evidence, and no current config has them.

    - lnbLo L: a receive-only LNB with RX offset L, selected. L = 9750 MHz
      (the old default, so almost everyone) is the "QO-100: LNB 9750 MHz"
      preset itself, which is also the default list: an old file and a
      fresh install end up with the same entry under the same name.
    - upconverterLo U: a TX-only converter with offset U, inverted when the
      side was high, selected for the IC-9700; a low-side LO a preset has
      takes that preset's name. No LO stays no converter, so the IC-9700
      path is still refused until one is chosen, as it was.

    A file that already has `converters` was written by hand with both
    sets of keys: the new ones win and the old are dropped.

    Then the uplink presets' retyping (`_uplink_presets_tx_only`).
    """
    old = {k: raw.pop(k) for k in ("lnbLo", "upconverterLo", "upconverterSide") if k in raw}
    if old and "converters" not in raw:
        _from_old_keys(raw, old, notes)
    return _uplink_presets_tx_only(raw)


UPLINK_PRESETS = {c.title.casefold(): c for c in cv.QO100 if c.use == cv.TX}


def _uplink_presets_tx_only(raw: dict) -> dict:
    """The three QO-100 uplink presets were RX/TX until 07/10/2026 and are
    TX only now (ohscore/converters.py says why). A copy stored before -
    `rxtx` true, no `use`, and every number still the preset's - becomes
    TX only. Nothing it does changes: NB transmits through it with the same
    TX offset, and it could never be the LNB (the downlink through it is
    nowhere near what the SDR tunes, so rx_ok refused it then as now). An
    entry the operator changed, or one already carrying `use` (a choice
    made since), is left alone: this is a rename of a preset, not a rule."""
    convs = raw.get("converters")
    if not isinstance(convs, list):
        return raw
    out = []
    for d in convs:
        p = UPLINK_PRESETS.get(str(d.get("title", "")).strip().casefold()) if isinstance(d, dict) else None
        if (p is not None and "use" not in d and d.get("rxtx") is True and d.get("type", cv.DOWN) == p.type
                and d.get("inverted", False) is False and d.get("rxOffset") == p.tx_offset
                and d.get("txOffset", d.get("rxOffset")) == p.tx_offset):
            d = {k: v for k, v in d.items() if k != "rxtx"}
            d["use"] = cv.TX
        out.append(d)
    raw["converters"] = out
    return raw


def _from_old_keys(raw: dict, old: dict, notes: list[str]) -> None:
    convs: list[dict] = []
    lnb = old.get("lnbLo")
    if _hz(lnb, 9_000_000_000.0, 10_400_000_000.0):
        lnb = float(lnb)
        title, preset = _title_for(lnb, f"QO-100: LNB {lnb / 1e6:.6f}".rstrip("0").rstrip(".") + " MHz", False)
        convs.append((preset or cv.Converter(title, cv.DOWN, cv.RX, lnb, lnb)).to_dict())
        raw["rxConverter"] = title
    elif lnb is not None:
        notes.append(f"lnbLo {lnb!r} was not a frequency an LNB has; using {LNB_DEFAULT.title}")
    if not convs:
        convs.append(LNB_DEFAULT.to_dict())
        raw["rxConverter"] = LNB_DEFAULT.title
    up = old.get("upconverterLo")
    if _hz(up, 100_000_000.0, 6_000_000_000.0):
        up = float(up)
        high = old.get("upconverterSide") == "high"
        title, preset = _title_for(up, f"IC-9700 upconverter (LO {up / 1e6:.6f}".rstrip("0").rstrip(".") +
                                   (" MHz, high-side)" if high else " MHz)"), True, high)
        # TX only, as the presets are: the IC-9700's upconverter only
        # transmits (it was RX/TX until 07/10/2026; nothing it does changed).
        convs.append((preset or cv.Converter(title, cv.DOWN, cv.TX, up, up, inverted=high)).to_dict())
        raw["rigTxConverter"] = title
    elif up is not None:
        notes.append(f"upconverterLo {up!r} was not a frequency; choose the IC-9700's upconverter again")
    raw["converters"] = convs


def _hz(v, lo: float, hi: float) -> bool:
    return (not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v))
            and lo <= float(v) <= hi)
