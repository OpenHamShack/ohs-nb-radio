"""The power chain: from the engine's *drive* to watts at the antenna
(docs/ham/DESIGN-HAM.md section 6, rule 6).

The engine knows drive, 0..1 of the device's full output amplitude; the
licence talks about watts PEP (or ERP/EIRP) at the antenna. Between them,
per band, an operator-entered chain:

    PEP at antenna = device output at full drive x (drive x mode peak)^2
                     x PA gain x feeder loss

(mode peak: 1, except AM's 0.5 - envelope_peak below.)

- **device output at full drive**: what the device says (`tx_full_w`) unless
  the operator has measured it and entered `devW`. A Pluto gives about
  +6.5 dBm, 4.5 mW (kittenlabs, one source - docs/qo100-research.md
  section 4; "far less at the extremes" is unmeasured); the Hermes-Lite 2
  about 5 W on every HF band (its FAQ).
- **PA gain** in dB (`paGainDb`, 0 = no PA: the device barefoot);
- **feeder loss** in dB (`lossDb`);
- **antenna gain** in dBi (`antGainDbi`), needed only where the licence's
  limit is ERP or EIRP (430-432 MHz, 60 m);
- **drive ceiling** (`ceiling`, 0..1): the most drive any control may set
  on this band, settable only from Settings (rule 5).

Every number here is an **estimate** unless measured: the UI says so. A
band with no chain entered transmits at the device's barefoot power, which
the estimate then reflects exactly as far as the device's own figure does.
"""
from __future__ import annotations

import math

from ohsradio.i18n import _

DEFAULT = {"devW": None, "paGainDb": 0.0, "lossDb": 0.0, "antGainDbi": 0.0, "ceiling": 1.0}
LIMITS = {"devW": (1e-6, 2000.0), "paGainDb": (0.0, 70.0), "lossDb": (0.0, 20.0), "antGainDbi": (-10.0, 40.0),
          "ceiling": (0.0, 1.0)}


def chain(power: dict, band: str) -> dict:
    out = dict(DEFAULT)
    out.update((power or {}).get(band, {}))
    return out


def clean(value: dict) -> dict:
    """Validate a persisted bandPower value ({band: {field: number}}):
    ValueError with a sentence on anything out of range. The licence guard
    trusts these numbers, so a bad one is refused, never clamped."""
    from .bands import BY_NAME
    out = {}
    for band, c in value.items():
        if band not in BY_NAME:
            raise ValueError(_("bandPower: no band called {band}").format(band=repr(band)))
        if not isinstance(c, dict):
            raise ValueError(_("bandPower {band}: must be a set of numbers").format(band=band))
        row = {}
        for k, v in c.items():
            if k not in LIMITS:
                raise ValueError(_("bandPower {band}: unknown field {field}").format(band=band, field=repr(k)))
            if v is None and k == "devW":
                row[k] = None
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                raise ValueError(_("bandPower {band}: {field} must be a number").format(band=band, field=k))
            lo, hi = LIMITS[k]
            if not lo <= float(v) <= hi:
                raise ValueError(_("bandPower {band}: {field} must be between {lo:g} and {hi:g}").format(
                    band=band, field=k, lo=lo, hi=hi))
            row[k] = float(v)
        out[band] = row
    return out


def full_pep(c: dict, device_full_w: float) -> float:
    """PEP at the antenna at full drive."""
    dev = c["devW"] if c.get("devW") else device_full_w
    return dev * 10 ** (c["paGainDb"] / 10) * 10 ** (-c["lossDb"] / 10)


def envelope_peak(mode: str) -> float:
    """The most of DAC full scale a mode's envelope reaches. 1 except AM,
    which is held at -6 dBFS (ohscore/dsp/mod.py AmMod explains why): its PEP
    at a given drive is a quarter of every other mode's."""
    if mode == "am":
        from ohscore.dsp.mod import AmMod
        return AmMod.PEAK
    return 1.0


def pep(c: dict, device_full_w: float, drive: float, mode: str = "") -> float:
    return full_pep(c, device_full_w) * (max(0.0, drive) * envelope_peak(mode)) ** 2


def drive_to_db(drive: float) -> float:
    """Drive (amplitude, 0..1) as a device gain in dB, for devices whose
    transmit level is an attenuator (the Pluto: -89.75..0 dB)."""
    if drive <= 0:
        return -89.75
    return max(-89.75, min(0.0, 20 * math.log10(drive)))
