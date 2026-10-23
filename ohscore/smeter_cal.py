"""S-meter calibration, held where every reader of one radio agrees: an
app's own state registry (Radio: `sMeterCal`, ohsradio/state.py), not a
desktop window's local preferences.

Before 23/10/2026 this lived in ohscore/ui/smeter.py's own ui.json
preference, `sMeterCal`, so only the window that made a calibration ever
saw it - OpenHamShack Remote and the store web page, reading the same
radio over the API, had no calibration at all and always showed dBFS or
UNCAL. Brian asked for it server-side so every reader (desktop Radio, the
store page, Remote) shows the same calibrated S-units. The math does not
change; only where the result is kept does. This module holds that math
with no PyQt import, so it loads in `python3 -m ohsradio --server`
(headless, often with no Qt platform plugin at all); ohscore/ui/smeter.py
imports it for the desktop widget, and ohsradio/radio.py for the engine
and the store API.

A calibration is per device, band and (new here) antenna input: the
front-end gain it was made at, corrected dB-for-dB for a later manual
gain change, and reported as not holding while the receiver's own AGC
chooses the gain (then nobody knows it to correct for). See `device_key`
for the antenna decision.

Stored as one line of JSON (`{key: {"offset", "gain", "when"}, ...}`),
the pattern ohscore/antennas.py uses for antenna labels, for the same
reason: a store container's settings reach it one variable per line, so
a value may not contain a line break, and JSON already escapes one
inside itself without this module inventing its own escaping.
"""
from __future__ import annotations

import json
import math

from .i18n.text import _

# IARU Region 1 Technical Recommendation "S-meter readings", Brighton 1981,
# Torremolinos 1990 (docs/ham/bandplan-r1-uk.md section 6 quotes it): S9 is
# -73 dBm below 30 MHz, -93 dBm at and above.
HF_TOP_HZ = 30e6
S9_HF_DBM = -73.0
S9_VHF_DBM = -93.0
DB_PER_S = 6.0

# "A plausible dBm range" (the brief): -140 dBm is below the thermal noise
# floor of any amateur receive bandwidth even at absolute zero, so nothing
# genuine reads below it; +30 dBm (1 W) is already enough to cook a front
# end, so nothing calibrated should read above it either. Generous on both
# sides, because the point is to catch a typo (a stray zero, a sign left
# off) or a dBW/dBuV figure pasted in by mistake, not to second-guess a
# real extreme.
PLAUSIBLE_DBM_LO = -140.0
PLAUSIBLE_DBM_HI = 30.0


def validate_dbm(value) -> float:
    """A `dbm` the API was given: a finite number in the plausible range.
    Raises ValueError with a sentence otherwise - the API's `bad_params`."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(_("dbm must be a number")) from None
    if not math.isfinite(v) or not PLAUSIBLE_DBM_LO <= v <= PLAUSIBLE_DBM_HI:
        raise ValueError(_("dbm must be a plausible level, {lo:g}..{hi:g} dBm").format(
            lo=PLAUSIBLE_DBM_LO, hi=PLAUSIBLE_DBM_HI))
    return v


def validate_dbfs(value) -> float:
    """A `dbfs` the API was given: a finite number (no range check - the
    engine's own scale already catches an impossible one through
    `calibrate`'s clipping and no-reading checks)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(_("dbfs must be a number")) from None
    if not math.isfinite(v):
        raise ValueError(_("dbfs must be a number"))
    return v


def s9_dbm(freq_hz: float) -> float:
    """S9 in dBm for a dial frequency."""
    return S9_HF_DBM if 0 < float(freq_hz or 0) < HF_TOP_HZ else S9_VHF_DBM


def s_text(dbm: float, s9: float) -> str:
    """'S7', 'S9', 'S9+12'. Below S9 the nearest S-unit; above it, whole dB
    over S9, the universal practice (ohscore/ui/smeter.py had this first;
    kept byte for byte so the desktop and the API never disagree)."""
    over = dbm - s9
    if over >= 0.5:
        return f"S9+{int(math.floor(over + 0.5))}"
    return f"S{max(0, min(9, int(math.floor(9 + over / DB_PER_S + 0.5))))}"


def device_key(st: dict) -> str:
    """Which radio a calibration belongs to: the device, its address (so two
    of a kind are told apart) and, where the driver has more than one
    antenna input, which one is in use.

    The antenna is part of the key (added 23/10/2026, Brian's ask): an
    RSPdx's three inputs do not share one front end end to end - cable
    loss and a transverter or preamp on one input but not another move
    the reading exactly as a gain change would, and nothing here can
    correct for that automatically the way it corrects for the receiver's
    own gain. Leaving it out would let a calibration made on "Antenna A"
    silently stand for "Antenna C" too, which is worse than asking for a
    second calibration when the input changes - and switching antenna
    input is already a live, no-restart setting (ohscore/devices/
    sdrsource.py), not a once-per-session choice, so the saving from
    sharing one calibration across inputs would be small. A device with
    one input (a Pluto, the HL2) never reports one, so its key is
    unchanged."""
    dev = str(st.get("device") or "sim")
    addr = {"pluto": st.get("plutoUri"), "libresdr": st.get("plutoUri"), "soapy": st.get("soapyArgs"),
            "hl2": st.get("hl2Address"), "rtlsdr": st.get("sdrSerial"), "sdrplay": st.get("sdrSerial")}.get(dev) or ""
    key = f"{dev}:{addr}" if addr else dev
    antenna = str(st.get("soapyAntenna") or "")
    return f"{key}@{antenna}" if antenna else key


def cal_key(st: dict) -> str | None:
    """device_key, and the band (the status `band`; absent apps like NB
    have none). None between bands: there is no band to have calibrated."""
    band = st.get("band")
    if band is None:
        return device_key(st)
    return f"{device_key(st)}|{band}" if band else None


def extra_stage(st: dict) -> tuple[str, float] | None:
    """A gain stage besides the one `known_gain` reports and `effective`
    corrects dB for dB - for the SDRplay RSP family (device `sdrplay`),
    the LNA state, `sdrplayLna`.

    It is not folded into `known_gain` and corrected the same way because
    its steps are not a fixed number of dB: how much a step of
    `sdrplayLna` attenuates depends on the band and the RSP model (the
    API gives states, not dB), unlike `rxGain`'s manual gain, which is
    linear by construction. So a calibration records this stage's own
    setting and holds only while it is unchanged - reported as not
    holding otherwise, the same as the receiver's own AGC being on,
    rather than silently wrong. Measured on ohs-box (Brian, 23/10/2026):
    an RSPdx on 2 m, rxGain 40, sdrplayLna 4, calibrated from a repeater
    ident; moving `rxGain` is corrected for, moving `sdrplayLna` is not.

    Other devices have one gain stage (a Pluto's rxGain, the HL2's
    hl2Lna) and so have no entry here. Add one if a device gains a
    second stage whose steps are not linear in dB."""
    if st.get("device") == "sdrplay":
        return "sdrplayLna", float(st.get("sdrplayLna", 4))
    return None


_STAGE_LABELS = {"sdrplayLna": lambda: _("the RSP's LNA state")}


def known_gain(st: dict) -> float | None:
    """The receiver's front-end gain in dB, if the program knows it. The
    Hermes-Lite 2 has only its LNA setting; a Pluto or SoapySDR radio knows
    its gain only when it is manual; the simulator's AGC choices are its
    40 dB reference gain, so it always knows."""
    dev = st.get("device") or "sim"
    if dev == "hl2":
        return float(st.get("hl2Lna", 20.0))
    if st.get("rxGainMode") == "manual":
        return float(st.get("rxGain", 40.0))
    if dev == "sim":
        from .devices.simcore import SimCore
        return float(SimCore.RX_GAIN_REF_DB)
    return None


def clean_cal(d) -> dict:
    """The stored calibrations, keeping only well-formed entries - a
    hand-edited setting, or a stray non-JSON value, costs one calibration,
    never the meter. Takes the single-line JSON a setting holds, or a
    dict already parsed (ohscore/ui/smeter.py's desktop prefs path)."""
    if isinstance(d, str):
        d = parse_cal(d)
    out = {}
    if not isinstance(d, dict):
        return out
    for k, rec in d.items():
        try:
            off, gain = float(rec["offset"]), float(rec["gain"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (isinstance(k, str) and math.isfinite(off) and math.isfinite(gain) and -250 <= off <= 250):
            continue
        entry = {"offset": off, "gain": gain, "when": str(rec.get("when", ""))}
        name, value = rec.get("extraName"), rec.get("extraValue")
        if isinstance(name, str) and name:
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None
            if value is not None and math.isfinite(value):
                entry["extraName"], entry["extraValue"] = name, value
        out[k] = entry
    return out


def parse_cal(raw: str) -> dict:
    """The table `format_cal` wrote back from its one-line JSON, or {} for
    empty or corrupt JSON (ohscore/antennas.py's parse_labels is the same
    pattern, for the same setting-is-one-line reason)."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return clean_cal(data)


def format_cal(cal: dict) -> str:
    """The single-line form stored in the setting. `ensure_ascii` is off so
    a band name is kept readable rather than escaped; the line still has
    no line break since json.dumps escapes one inside a string."""
    clean = clean_cal(cal)
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":")) if clean else ""


_DEVICE_NAMES = {
    "sim": lambda: _("the simulator"), "pluto": lambda: _("the Pluto"), "soapy": lambda: _("the SoapySDR radio"),
    "libresdr": lambda: _("the LibreSDR"), "rtlsdr": lambda: _("the RTL-SDR"), "sdrplay": lambda: _("the SDRplay RSP"),
    "hl2": lambda: _("the Hermes-Lite 2")}


def where_text(st: dict) -> str:
    s = _DEVICE_NAMES.get(st.get("device") or "sim", lambda: str(st.get("device")))()
    if st.get("soapyAntenna"):
        s = _("{radio} on {antenna}").format(radio=s, antenna=st["soapyAntenna"])
    if st.get("band"):
        s = _("{radio} on {band}").format(radio=s, band=st["band"])
    return s


def _calibrate_hint() -> str:
    return _("Right-click the meter › Calibrate…")


class CalState:
    """The offset to add to dBFS for dBm now, whether it may be called
    calibrated, a sentence saying why (for a tooltip, Settings or the
    meter item's `whyText`), and a short code for the same reason
    (`whyCode`: a client that wants its own wording can key off this
    instead of matching English text)."""

    def __init__(self, offset: float, ok: bool, why: str, why_code: str = "", stored: dict | None = None):
        self.offset, self.ok, self.why, self.why_code, self.stored = offset, ok, why, why_code, stored


def effective(store, st: dict) -> CalState:
    key = cal_key(st)
    if key is None:
        return CalState(0.0, False, _(
            "Uncalibrated: calibration is per band, and the dial is between bands."), "between_bands")
    rec = clean_cal(store).get(key)
    if rec is None:
        return CalState(0.0, False, _(
            "Uncalibrated: no calibration for {radio} yet.").format(radio=where_text(st))
            + " " + _calibrate_hint(), "no_calibration")
    g = known_gain(st)
    if g is None:
        return CalState(rec["offset"], False, _(
            "Uncalibrated now: the receiver's own AGC is on, so its gain is unknown and no calibration holds. Set "
            "Receiver gain control to Manual (Settings › Radio)."), "agc", rec)
    stage = extra_stage(st)
    if stage is not None:
        name, value = stage
        if rec.get("extraName") != name or rec.get("extraValue") is None or \
                abs(float(rec["extraValue"]) - value) > 1e-9:
            label = _STAGE_LABELS.get(name, lambda: name)()
            return CalState(rec["offset"], False, _(
                "Uncalibrated now: {stage} has changed since this radio was calibrated, and that cannot be "
                "corrected for the way a manual gain change is. Calibrate again.").format(stage=label),
                "extra_changed", rec)
    off = rec["offset"] - (g - rec["gain"])
    corrected = abs(g - rec["gain"]) > 1e-9
    if rec["when"] and corrected:
        why = _("Calibrated {when} at {gain} dB receiver gain, corrected for {now} dB now.")
    elif rec["when"]:
        why = _("Calibrated {when} at {gain} dB receiver gain.")
    elif corrected:
        why = _("Calibrated at {gain} dB receiver gain, corrected for {now} dB now.")
    else:
        why = _("Calibrated at {gain} dB receiver gain.")
    return CalState(off, True, why.format(when=rec["when"], gain=f"{rec['gain']:g}", now=f"{g:g}"), "", rec)


def calibrate(store, st: dict, measured_dbfs: float | None, known_dbm: float, when: str = "") -> dict:
    """The table with the offset added that makes `measured_dbfs` read
    `known_dbm` for this radio (band, antenna), at its current gain.
    Raises ValueError with the reason it cannot."""
    key = cal_key(st)
    if key is None:
        raise ValueError(_("The dial is between bands; tune into a band to calibrate it."))
    g = known_gain(st)
    if g is None:
        raise ValueError(_(
            "The receiver's own AGC is on, so its gain moves with the signal and no offset would hold. Set "
            "Receiver gain control to Manual (Settings › Radio) and calibrate again."))
    if measured_dbfs is None or measured_dbfs <= -199:
        raise ValueError(_("There is no reading to calibrate against."))
    if measured_dbfs > -3.0:
        raise ValueError(_(
            "The receiver is within 3 dB of full scale and may be clipping; lower its gain or the signal."))
    out = clean_cal(store)
    entry = {"offset": round(known_dbm - measured_dbfs, 2), "gain": g, "when": when}
    stage = extra_stage(st)
    if stage is not None:
        entry["extraName"], entry["extraValue"] = stage
    out[key] = entry
    return out


def forget(store, st: dict) -> dict:
    """The table with this radio's (band's, antenna's) entry removed."""
    out = clean_cal(store)
    out.pop(cal_key(st) or "", None)
    return out


def average_dbfs(hist) -> tuple[float, float] | None:
    """(power mean of a short history of dBFS readings, half its spread in
    dB), or None for an empty history - the "current reading" behind
    Calibrate… and `{"dbm": ...}` on the API (docs/SERVER-API.md):
    averaging a couple of seconds rides over the meter's own ballistics
    rather than calibrating against one noisy instant."""
    if not hist:
        return None
    lin = [10 ** (v / 10) for v in hist]
    return 10 * math.log10(sum(lin) / len(lin)), (max(hist) - min(hist)) / 2
