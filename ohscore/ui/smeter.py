"""The S-meter: the Receive card's Signal meter, in three styles and five units.

What it measures has not changed: the engine's `rx`, the power in the
receive passband in dBFS (ohscore/dsp/demod.py, taken before the AGC and the
manual RF gain, so neither moves it). Everything here is how that one
number is *said*:

- **dBFS**, the engine's own figure and the default, so an operator who
  never touches the meter sees what the program always showed.
- **S-units** and **dBm**, by IARU Region 1's Technical Recommendation
  (Brighton 1981, Torremolinos 1990; docs/ham/bandplan-r1-uk.md §6 quotes
  it): S9 is
  -73 dBm below 30 MHz and -93 dBm above, one S-unit is 6 dB. A dBFS figure
  becomes dBm only through a calibration offset, which depends on the radio,
  its gain and (NB) the LNB. Until one holds, these two units do NOT show an
  absolute figure at all: they show UNCAL and the *relative* reading the
  program can honestly stand behind - dB over noise when the zoom spectrum
  has a noise floor, else dBFS - on that unit's own scale. History: they once
  read on a nominal 0 dBFS = 0 dBm, so a Pluto behind a QO-100 LNB showed an
  ordinary -21 dBFS transponder signal as "S9+72" (VHF S9 is -93 dBm); an
  UNCAL chip beside an absurd number was not enough, because the number is
  what gets read, quoted and believed. Anchoring the S scale on the noise
  floor (noise = S1) was considered and rejected for the same reason: it is
  still an invented S figure, and a QO-100 operator has no use for one. The
  tooltip says how to calibrate. The needle still moves, on the relative
  scale (`shown_unit`).
- **dB over noise**: the passband's power against the noise that would be
  in the same passband, from the zoom spectrum's median - the floor the
  "SNR in passband" meter already uses (ohscore/ui/window.py), converted
  from one bin's width to the passband's (passband_noise_dbfs).
- **dB vs beacon** (QO-100 NB only, Face.smeter_beacon): the passband
  against the beacon's level as beacon lock measures it - on QO-100 the
  one reference every station shares. It was NB's default unit until
  "S (beacon ref)" below took its place (Face.smeter_default_unit; Prefs
  stores "" until the operator chooses, so a stored choice, even "dbfs",
  always beats the default).
- **S (beacon ref)** (QO-100 NB only, and its default since the overhaul of
  October 2026, decision 10): the same comparison said in S-units, S = 9 +
  (passband dB - beacon dB) / 6, so the middle beacon reads S9 with no
  calibration at all and a signal 12 dB under it S7. An operator reads "S7"
  at a glance where "-12.0 dB vs beacon" needs a sum; and unlike S-units on
  a nominal calibration it is a figure another QO-100 station can check,
  because they hear the same beacon. Neither the AGC nor the receiver gain
  moves it: the passband level is taken before the AGC (above), and the
  beacon's level is measured by beacon lock from the same receive IQ
  (ohsnb/dsp/lock.py), so any gain ahead of both cancels.

Red on the scale means our own signal (docs/ui-overhaul-2026-10.md section
5.3). The zone beyond S9 / above the beacon is drawn neutral while receiving
- another station loud on the band is not a danger - and red only while we
are on the air (Face.on_air), when what fills the passband is our own
downlink and above the beacon is where it must not be. Before, a strong
signal heard on an idle receiver read "S9+53" in red.

Calibration is per radio (the device and its address) and, in OpenHamShack Radio,
per band, because a Pluto's gain at 2 m and at 23 cm differ by more than an
S-unit. It records the front-end gain it was made at; a later manual gain
change is accounted for dB for dB (dBFS moves one-for-one with the gain of
a linear front end), so turning the gain does not need a recalibration. A
receiver whose own AGC is on has a gain nobody here knows, so there the
calibration is reported as not holding rather than silently wrong. It is a
window preference (ui.json, `sMeterCal`), not an engine setting: the engine
never needs dBm, and keeping it out of the state registry keeps it out of
the transmit path entirely.

Ballistics follow the same recommendation: quasi-peak, 10 ms attack and a
decay time constant of at least 500 ms. The engine's meter feed is 10 Hz,
so the attack is in practice "at the next frame"; the decay is the
Ballistic's release of 2 per second. The motion is integrated in position
along the scale (0..1), so a needle swings the same way whatever the unit.

Paint cost matters - the meter repaints at the display rate while it moves.
The analogue dial's face (scale, ticks) and its glass (shroud and the
legend printed on it, glare) are pixmaps rebuilt only when the size, theme, unit or band rule
changes; a frame is two blits and two lines.
"""
from __future__ import annotations

import math
import re
import time
from collections import deque

from PyQt6.QtCore import QCoreApplication, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (QBrush, QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                         QRadialGradient)
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QMenu, QVBoxLayout

from . import theme
from .controls import mix
from .meters import Ballistic, BarMeter

# ------------------------------------------------------------- the standard
# IARU Region 1 Technical Recommendation "S-meter readings", Brighton 1981,
# Torremolinos 1990, as printed in the IARU-R1 VHF Handbook v10.03 (Feb 2026)
# p. 104. "Below 30 MHz" is HF; everything from 30 MHz up takes the VHF level
# (the box says "above 30 MHz"; the prose beside it notes 30-144 MHz was once
# left open - the box is the text that was adopted).
HF_TOP_HZ = 30e6
S9_HF_DBM = -73.0
S9_VHF_DBM = -93.0
DB_PER_S = 6.0

STYLES = ("bar", "analog", "digital")
STYLE_NAMES = {"bar": "Bar", "analog": "Analogue", "digital": "Digital"}
UNITS = ("s", "dbm", "dbfs", "snr", "beacon", "sbeacon")
UNIT_NAMES = {"s": "S-units", "dbm": "dBm", "dbfs": "dBFS", "snr": "dB over noise", "beacon": "dB vs beacon",
              "sbeacon": "S (beacon ref)"}
# The units that read against the beacon, offered only where there is one
# (Face.smeter_beacon).
BEACON_UNITS = ("beacon", "sbeacon")
DEFAULTS = {"sMeterStyle": "bar", "sMeterUnit": "", "sMeterPeak": True, "sMeterCal": {}}

# The analogue scale's sweep, degrees either side of upright.
HALF_SWEEP = 55.0


def s9_dbm(freq_hz: float) -> float:
    """S9 in dBm for a dial frequency. QO-100 NB's dial is the 10 GHz
    downlink, so it always takes the VHF level; HAM's follows the band."""
    return S9_HF_DBM if 0 < float(freq_hz or 0) < HF_TOP_HZ else S9_VHF_DBM


def s_units(dbm: float, s9: float) -> float:
    return 9.0 + (dbm - s9) / DB_PER_S


def s_text(dbm: float, s9: float) -> str:
    """'S7', 'S9', 'S9+12'. Below S9 the nearest S-unit (a receiver's needle
    between S6 and S7 is read as the nearer); above it, whole dB over S9,
    the universal practice."""
    over = dbm - s9
    if over >= 0.5:
        return f"S9+{int(math.floor(over + 0.5))}"
    return f"S{max(0, min(9, int(math.floor(9 + over / DB_PER_S + 0.5))))}"


def dbm_from_microvolts(uv: float) -> float:
    """Available power of an EMF-matched source reading `uv` across 50 ohms
    (the signal-generator convention the recommendation's 50 uV = S9 uses)."""
    v = uv * 1e-6
    return 10 * math.log10(v * v / 50.0 / 1e-3)


def parse_level(text: str, s9: float) -> float:
    """A typed signal level -> dBm: '-73', '-73 dBm', 'S9', 'S9+20', 's7',
    '50 uV' / '50 µV'. ValueError with a sentence otherwise."""
    t = text.strip().lower().replace("−", "-").replace(" ", "").replace("µ", "u")
    m = re.fullmatch(r"s([0-9])(?:\+([0-9]+(?:\.[0-9]+)?)(?:db)?)?", t)
    if m:
        n, over = int(m.group(1)), float(m.group(2) or 0.0)
        if over and n != 9:
            raise ValueError(QCoreApplication.translate("SMeter", "Only S9 takes '+dB' (S9+20)."))
        return s9 + (n - 9) * DB_PER_S + over
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)uv", t)
    if m:
        uv = float(m.group(1))
        if uv <= 0:
            raise ValueError(QCoreApplication.translate("SMeter", "A level in microvolts must be above zero."))
        return dbm_from_microvolts(uv)
    m = re.fullmatch(r"(-?[0-9]+(?:\.[0-9]+)?)(?:dbm)?", t)
    if m:
        v = float(m.group(1))
        if not -200.0 <= v <= 30.0:
            raise ValueError(QCoreApplication.translate("SMeter", "That level is outside -200..+30 dBm."))
        return v
    raise ValueError(QCoreApplication.translate(
        "SMeter", "Type a level as dBm (-73), an S reading (S9, S9+20) or microvolts (50 uV)."))


def passband_noise_dbfs(median_bin_db: float, bin_hz: float, bw_hz: float, avg: int) -> float:
    """The noise power a passband `bw_hz` wide would hold, in the dBFS the
    engine's passband meter uses, from the median of a spectrum line made
    by ohscore.dsp.spectrum.Scope (Hann window, normalised so a tone reads
    its power, `avg` frames averaged per line).

    One bin of that Scope holds noise density x bin_hz x 1.5 (the Hann
    window's equivalent noise bandwidth in bins). The median of averaged
    power is below its mean (an exponential's median is ln 2, -1.6 dB, for
    one frame; less as frames average); the Wilson-Hilferty approximation of
    a chi-squared median with 2 x avg degrees of freedom puts that back."""
    k = 2.0 * max(1, int(avg))
    median_over_mean = (1.0 - 2.0 / (9.0 * k)) ** 3
    return (median_bin_db - 10 * math.log10(median_over_mean) - 10 * math.log10(1.5 * bin_hz)
            + 10 * math.log10(max(1.0, bw_hz)))


# ------------------------------------------------------------ calibration
def device_key(st: dict) -> str:
    """Which radio a calibration belongs to: the device, and the address
    that tells two of a kind apart. A Pluto on USB is always
    ip:192.168.2.1, so two of those share one calibration - which is the
    best the program can tell."""
    dev = str(st.get("device") or "sim")
    addr = {"pluto": st.get("plutoUri"), "libresdr": st.get("plutoUri"), "soapy": st.get("soapyArgs"),
            "hl2": st.get("hl2Address"), "rtlsdr": st.get("sdrSerial"), "sdrplay": st.get("sdrSerial")}.get(dev) or ""
    return f"{dev}:{addr}" if addr else dev


def cal_key(st: dict) -> str | None:
    """device_key, and in OpenHamShack Radio the band (its status `band`; NB has
    none). None between bands: there is no band to have calibrated."""
    band = st.get("band")
    if band is None:
        return device_key(st)
    return f"{device_key(st)}|{band}" if band else None


def known_gain(st: dict) -> float | None:
    """The receiver's front-end gain in dB, if the program knows it. The
    Hermes-Lite 2 has only its LNA setting; a Pluto or SoapySDR radio knows
    its gain only when it is manual; the simulator's AGC choices are its
    40 dB reference gain (ohscore/devices/simcore.py), so it always knows."""
    dev = st.get("device") or "sim"
    if dev == "hl2":
        return float(st.get("hl2Lna", 20.0))
    if st.get("rxGainMode") == "manual":
        return float(st.get("rxGain", 40.0))
    if dev == "sim":
        from ..devices.simcore import SimCore
        return float(SimCore.RX_GAIN_REF_DB)
    return None


def clean_cal(d) -> dict:
    """The stored calibrations, keeping only well-formed entries: a
    hand-edited ui.json costs one calibration, never the meter."""
    out = {}
    if not isinstance(d, dict):
        return out
    for k, rec in d.items():
        try:
            off, gain = float(rec["offset"]), float(rec["gain"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(k, str) and math.isfinite(off) and math.isfinite(gain) and -250 <= off <= 250:
            out[k] = {"offset": off, "gain": gain, "when": str(rec.get("when", ""))}
    return out


class CalState:
    """The offset to add to dBFS for dBm now, whether it may be called
    calibrated, and a sentence saying why (for the tooltip and Settings)."""

    def __init__(self, offset: float, ok: bool, why: str, stored: dict | None = None):
        self.offset, self.ok, self.why, self.stored = offset, ok, why, stored


def where_text(st: dict) -> str:
    # Built when called, not at import, so the names are looked up after
    # the window's catalog is installed.
    names = {"sim": QCoreApplication.translate("SMeter", "the simulator"),
             "pluto": QCoreApplication.translate("SMeter", "the Pluto"),
             "soapy": QCoreApplication.translate("SMeter", "the SoapySDR radio"),
             "libresdr": QCoreApplication.translate("SMeter", "the LibreSDR"),
             "rtlsdr": QCoreApplication.translate("SMeter", "the RTL-SDR"),
             "sdrplay": QCoreApplication.translate("SMeter", "the SDRplay RSP"),
             "hl2": QCoreApplication.translate("SMeter", "the Hermes-Lite 2")}
    s = names.get(st.get("device") or "sim", str(st.get("device")))
    if st.get("band"):
        s = QCoreApplication.translate("SMeter", "{radio} on {band}").format(radio=s, band=st["band"])
    return s


def _calibrate_hint() -> str:
    """The pointer to Calibrate… that ends the not-calibrated sentence, and
    which Settings takes back out (it has its own button): one lookup for
    both, so the two agree in any language."""
    return QCoreApplication.translate("SMeter", "Right-click the meter › Calibrate…")


def effective(store: dict, st: dict) -> CalState:
    key = cal_key(st)
    if key is None:
        return CalState(0.0, False, QCoreApplication.translate(
            "SMeter", "Uncalibrated: calibration is per band, and the dial is between bands."))
    rec = clean_cal(store).get(key)
    if rec is None:
        return CalState(0.0, False, QCoreApplication.translate(
            "SMeter", "Uncalibrated: no calibration for {radio} yet.").format(radio=where_text(st))
            + " " + _calibrate_hint())
    g = known_gain(st)
    if g is None:
        return CalState(rec["offset"], False, QCoreApplication.translate(
            "SMeter", "Uncalibrated now: the receiver's own AGC is on, so its gain is unknown and no calibration "
            "holds. Set Receiver gain control to Manual (Settings › Radio)."), rec)
    off = rec["offset"] - (g - rec["gain"])
    # Four whole sentences rather than one grown clause by clause, so each
    # can be translated with its own word order.
    corrected = abs(g - rec["gain"]) > 1e-9
    if rec["when"] and corrected:
        why = QCoreApplication.translate("SMeter", "Calibrated {when} at {gain} dB receiver gain, corrected for "
                                                   "{now} dB now.")
    elif rec["when"]:
        why = QCoreApplication.translate("SMeter", "Calibrated {when} at {gain} dB receiver gain.")
    elif corrected:
        why = QCoreApplication.translate("SMeter", "Calibrated at {gain} dB receiver gain, corrected for {now} dB "
                                                   "now.")
    else:
        why = QCoreApplication.translate("SMeter", "Calibrated at {gain} dB receiver gain.")
    return CalState(off, True, why.format(when=rec["when"], gain=f"{rec['gain']:g}", now=f"{g:g}"), rec)


def calibrate(store: dict, st: dict, measured_dbfs: float, known_dbm: float, when: str = "") -> dict:
    """Store the offset that makes `measured_dbfs` read `known_dbm` for this
    radio (and band), at its current gain. Returns the new store; raises
    ValueError with the reason it cannot."""
    key = cal_key(st)
    if key is None:
        raise ValueError(QCoreApplication.translate(
            "SMeter", "The dial is between bands; tune into a band to calibrate it."))
    g = known_gain(st)
    if g is None:
        raise ValueError(QCoreApplication.translate(
            "SMeter", "The receiver's own AGC is on, so its gain moves with the signal and no offset would hold. "
            "Set Receiver gain control to Manual (Settings › Radio) and calibrate again."))
    if measured_dbfs is None or measured_dbfs <= -199:
        raise ValueError(QCoreApplication.translate("SMeter", "There is no reading to calibrate against."))
    if measured_dbfs > -3.0:
        raise ValueError(QCoreApplication.translate(
            "SMeter", "The receiver is within 3 dB of full scale and may be clipping; lower its gain or the "
            "signal."))
    out = clean_cal(store)
    out[key] = {"offset": round(known_dbm - measured_dbfs, 2), "gain": g, "when": when or time.strftime("%Y-%m-%d")}
    return out


def forget(store: dict, st: dict) -> dict:
    out = clean_cal(store)
    out.pop(cal_key(st) or "", None)
    return out


# ------------------------------------------------------------------ scales
class Scale:
    """A meter scale for one unit: value range, the position (0..1) of a
    value along it, labelled and minor ticks, coloured zones. `knee`
    (value, position) bends it: the S-unit scale gives S0-S9 the first 60 %
    and +60 dB the rest, as printed meters do."""

    def __init__(self, lo, hi, ticks, zones, knee=None):
        self.lo, self.hi, self.ticks, self.zones, self.knee = lo, hi, ticks, zones, knee

    def pos(self, v: float) -> float:
        v = max(self.lo, min(self.hi, v))
        if self.knee is None:
            return (v - self.lo) / ((self.hi - self.lo) or 1.0)
        kv, kp = self.knee
        if v <= kv:
            return kp * (v - self.lo) / ((kv - self.lo) or 1.0)
        return kp + (1 - kp) * (v - kv) / ((self.hi - kv) or 1.0)


# The zone token for "over S9 / over the beacon": not a colour of its own,
# resolved by the widget (SMeter.zone_colour) to red on the air and to the
# receive colour otherwise.
OVER = "over"


def scale_for(unit: str, s9: float) -> Scale:
    if unit in ("s", "dbm"):
        lo, hi = s9 - 9 * DB_PER_S, s9 + 60.0
        zones = ((lo, s9, "rx"), (s9, hi, OVER))
        if unit == "s":
            ticks = [(s9 - (9 - n) * DB_PER_S, str(n) if n % 2 else "", n % 2 == 1) for n in range(1, 10)]
            ticks += [(s9 + d, f"+{d}" if d in (20, 40, 60) else "", d in (20, 40, 60)) for d in (10, 20, 30, 40, 50, 60)]
            return Scale(lo, hi, ticks, zones, knee=(s9, 0.6))
        first = math.ceil(lo / 10) * 10
        ticks = [(v, f"{v:g}" if v % 20 == 0 else "", v % 20 == 0) for v in range(int(first), int(hi) + 1, 10)]
        return Scale(lo, hi, ticks, zones)
    if unit == "snr":
        return Scale(0.0, 60.0, [(v, f"{v}", True) for v in range(0, 61, 10)] +
                     [(v, "", False) for v in range(5, 60, 10)], ((0.0, 6.0, "warn"), (6.0, 60.0, "rx")))
    if unit == "beacon":
        return Scale(-40.0, 10.0, [(v, f"{v:+d}" if v else "0", True) for v in range(-40, 11, 10)] +
                     [(v, "", False) for v in range(-35, 10, 10)], ((-40.0, 0.0, "rx"), (0.0, 10.0, OVER)))
    if unit == "sbeacon":
        # dB against the beacon, laid out as the S scale with S9 at 0: S1-S9
        # the first 60 %, then to S9+40 (a downlink 40 dB over the beacon is
        # far beyond anything the transponder should carry; the needle pins).
        lo, hi = -9 * DB_PER_S, 40.0
        ticks = [(-(9 - n) * DB_PER_S, str(n) if n % 2 else "", n % 2 == 1) for n in range(1, 10)]
        ticks += [(float(d), f"+{d}" if d in (20, 40) else "", d in (20, 40)) for d in (10, 20, 30, 40)]
        return Scale(lo, hi, ticks, ((lo, 0.0, "rx"), (0.0, hi, OVER)), knee=(0.0, 0.6))
    # dBFS: today's scale, exactly.
    return Scale(-130.0, -30.0, [(v, f"{v:g}", True) for v in (-130, -110, -90, -70, -50, -30)] +
                 [(v, "", False) for v in (-120, -100, -80, -60, -40)], ((-130.0, -30.0, "rx"),))


def shown_unit(unit: str, cal: "CalState", noise=None) -> str:
    """The unit actually drawn. Uncalibrated S-units and dBm have no honest
    absolute figure, so they fall back to the relative reading: dB over
    noise, or dBFS while there is no noise floor yet."""
    if unit in ("s", "dbm") and not cal.ok:
        return "snr" if noise is not None else "dbfs"
    return unit


def resolve_unit(stored, units: tuple, default: str) -> str:
    """The unit in force: the operator's stored choice if it is offered
    here, else the app's default (Face.smeter_default_unit), else dBFS."""
    for u in (stored, default):
        if u in units:
            return u
    return "dbfs"


def needle_angle(pos: float) -> float:
    """Degrees from upright (positive to the right) for a scale position."""
    return -HALF_SWEEP + 2 * HALF_SWEEP * max(0.0, min(1.0, pos))


class Reading:
    """What the meter says for one dBFS figure in one unit: the value in that
    unit (None: nothing to say), its text, its secondary text, and whether
    the UNCAL mark belongs on it."""

    def __init__(self, value, text, unit_text, second="", uncal=False):
        self.value, self.text, self.unit_text, self.second, self.uncal = value, text, unit_text, second, uncal


def reading(unit: str, dbfs, s9: float, cal: CalState, noise=None, beacon=None) -> Reading:
    if unit in ("s", "dbm") and not cal.ok:
        # No absolute figure without a calibration (module docstring).
        r = reading(shown_unit(unit, cal, noise), dbfs, s9, cal, noise, beacon)
        r.uncal = True
        return r
    if dbfs is None:
        return Reading(None, "—", "")
    if unit in ("s", "dbm"):
        dbm = dbfs + cal.offset
        if unit == "s":
            return Reading(dbm, s_text(dbm, s9), "", f"{dbm:.0f} dBm")
        return Reading(dbm, f"{dbm:.1f}", "dBm", s_text(dbm, s9))
    if unit == "snr":
        if noise is None:
            return Reading(None, "—", QCoreApplication.translate("SMeter", "dB over noise"))
        v = max(0.0, dbfs - noise)
        return Reading(v, f"{v:.0f}", QCoreApplication.translate("SMeter", "dB over noise"), f"{dbfs:.1f} dBFS")
    if unit in BEACON_UNITS:
        name = (QCoreApplication.translate("SMeter", "dB vs beacon") if unit == "beacon" else "")
        if beacon is None or beacon <= -199:
            return Reading(None, "—", name, QCoreApplication.translate("SMeter", "no beacon level"))
        v = dbfs - beacon
        if unit == "sbeacon":
            # s_text with S9 at 0 dB: the middle beacon is S9 by definition.
            return Reading(v, s_text(v, 0.0), "", QCoreApplication.translate("SMeter", "{db} dB vs beacon").format(
                db=f"{v:+.1f}"))
        return Reading(v, f"{v:+.1f}", name, f"{dbfs:.1f} dBFS")
    return Reading(dbfs, f"{dbfs:.1f}", "dBFS")


# ------------------------------------------------------------------ widget
class _MemPrefs(dict):
    """Preferences for a meter built without the window's (a test, a tool)."""

    def save(self):
        pass


class SMeter(BarMeter):
    """The Receive card's Signal meter. A click on the reading cycles the
    unit, a click anywhere else the style; right-click for both, the
    peak-hold needle and Calibrate…. Built on BarMeter so the bar style is
    the bar every other meter is, painted by the same code."""

    HEIGHTS = {"bar": 50, "analog": 136, "digital": 66}

    def __init__(self, bridge=None, prefs=None, parent=None):
        # translate(), not self.tr(): the QWidget is not made until this returns.
        super().__init__(QCoreApplication.translate("SMeter", "Signal"), 0.0, 1.0)
        self.b = Ballistic(0.0, 1.0, attack=100.0, release=2.0)
        self.bridge = bridge
        self.prefs = prefs if prefs is not None else _MemPrefs(DEFAULTS)
        self.dbfs: float | None = None
        self.noise: float | None = None
        self.beacon: float | None = None
        self.hist: deque = deque(maxlen=30)        # 3 s of 10 Hz readings, for Calibrate…
        self.rd = Reading(None, "—", "")
        self.cal = CalState(0.0, False, "")
        self.scale = scale_for("dbfs", S9_VHF_DBM)
        self._s9 = S9_VHF_DBM
        self._face: tuple | None = None            # (key, face pixmap, glass pixmap)
        self.on_air = False                        # as of the last _refresh (own_on_air)
        self.paints = 0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_prefs()

    # --------------------------------------------------------- preferences
    def _st(self) -> dict:
        return self.bridge.st if self.bridge is not None else {}

    def beacon_ok(self) -> bool:
        face = getattr(self.bridge, "face", None)
        return bool(getattr(face, "smeter_beacon", False))

    def units(self) -> tuple:
        return tuple(u for u in UNITS if u not in BEACON_UNITS or self.beacon_ok())

    @property
    def style(self) -> str:
        v = self.prefs.get("sMeterStyle", "bar")
        return v if v in STYLES else "bar"

    @property
    def unit(self) -> str:
        return resolve_unit(self.prefs.get("sMeterUnit", ""), self.units(), self.default_unit())

    def default_unit(self) -> str:
        face = getattr(self.bridge, "face", None)
        return str(getattr(face, "smeter_default_unit", "dbfs"))

    @property
    def shown(self) -> str:
        """The unit on the scale and in the legend (shown_unit)."""
        return shown_unit(self.unit, self.cal, self.noise)

    @unit.setter
    def unit(self, _v):
        pass        # BarMeter's constructor assigns its own unit string; the S-meter's lives in prefs

    def apply_prefs(self):
        """After Settings, or a click: size, scale and reading follow the
        stored style and unit."""
        self.setFixedHeight(self.HEIGHTS[self.style])
        self._refresh()
        self.update()

    def set_pref(self, key: str, value):
        self.prefs[key] = value
        self.prefs.save()
        self.apply_prefs()

    def cycle_style(self):
        self.set_pref("sMeterStyle", STYLES[(STYLES.index(self.style) + 1) % len(STYLES)])

    def cycle_unit(self):
        us = self.units()
        self.set_pref("sMeterUnit", us[(us.index(self.unit) + 1) % len(us)])

    def own_on_air(self) -> bool:
        """Whether our own transmitter is radiating (Face.on_air, which with
        an IC-9700 is the radio's own word): the one time the zone beyond
        S9 / the beacon is red (module docstring)."""
        face = getattr(self.bridge, "face", None)
        if face is None or not hasattr(face, "on_air"):
            return False
        try:
            return bool(face.on_air(self._st()))
        except Exception:  # noqa: BLE001 - a meter never takes the card down over a colour
            return False

    def zone_colour(self, k: str) -> str:
        """A scale zone's token as painted now: OVER is red on the air and
        the receive colour otherwise; every other token is itself."""
        if k == OVER:
            return "err" if self.on_air else "rx"
        return k

    # --------------------------------------------------------------- feeds
    def feed(self, dbfs, beacon=None):
        """One meter-feed item: the passband level (None: no signal) and,
        in NB, the beacon's level."""
        self.dbfs = dbfs
        self.beacon = beacon
        if dbfs is not None:
            self.hist.append(float(dbfs))
        self._refresh()

    def set_value(self, v):          # BarMeter's interface, for anything that drives it as one
        self.feed(v, self.beacon)

    def set_noise(self, noise_dbfs):
        self.noise = noise_dbfs

    def average_dbfs(self) -> tuple[float, float] | None:
        """(power mean of the last 3 s in dBFS, half its spread in dB)."""
        if not self.hist:
            return None
        lin = [10 ** (v / 10) for v in self.hist]
        return 10 * math.log10(sum(lin) / len(lin)), (max(self.hist) - min(self.hist)) / 2

    def _refresh(self):
        st = self._st()
        s9 = s9_dbm(st.get("vfo", 0.0))
        self.cal = effective(self.prefs.get("sMeterCal") or {}, st)
        unit = self.shown
        on_air = self.own_on_air()
        if (s9 != self._s9 or self.scale is None or getattr(self, "_scale_unit", None) != unit
                or on_air != self.on_air):
            self._s9, self._scale_unit, self.on_air = s9, unit, on_air
            self.scale = scale_for(unit, s9)
            sc = self.scale
            self.ticks = [sc.pos(v) for v, lab, major in sc.ticks if lab]
            self._labels = {sc.pos(v): lab for v, lab, major in sc.ticks if lab}
            self.zones = [(sc.pos(a), sc.pos(z), self.zone_colour(k)) for a, z, k in sc.zones]
            self.update()
        self.rd = reading(self.unit, self.dbfs, s9, self.cal, self.noise, self.beacon)
        self.b.set(None if self.rd.value is None else self.scale.pos(self.rd.value))
        tip = self.tr("Click: next style · click the reading: next unit · right-click: menu.")
        if self.unit in ("s", "dbm"):
            tip = self.cal.why + "\n" + tip
            if not self.cal.ok:
                tip = self.tr("UNCAL: with no calibration no absolute level is shown, so this reads relative to "
                              "the noise (or dBFS). To calibrate: set Receiver gain control to Manual, feed a "
                              "signal of known level, then right-click the meter › Calibrate…") + "\n" + tip
        if tip != self.toolTip():
            self.setToolTip(tip)

    # ------------------------------------------------------------ BarMeter
    def value_text(self) -> str:
        on = self.active and self.rd.value is not None
        if not on:
            return "—"
        return self.rd.text + (" " + self.rd.unit_text if self.rd.unit_text else "")

    def tick_label(self, v: float) -> str:
        return self._labels.get(v, "")

    # --------------------------------------------------------------- mouse
    def unit_rect(self) -> QRectF:
        """Where a click changes the unit: the reading (bar, analogue) or
        the unit's name (digital)."""
        w = self.width()
        if self.style == "digital":
            return QRectF(w * 0.5, 0, w * 0.5, 18)
        fm = QFontMetricsF(theme.font(13, theme.QFont.Weight.DemiBold, mono=True))
        tw = max(64.0, fm.horizontalAdvance(self.value_text()) + 12)
        return QRectF(w - tw, 0, tw, 18)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.unit_rect().contains(e.position()):
            self.cycle_unit()
        else:
            self.cycle_style()

    def contextMenuEvent(self, e):
        self.menu().exec(e.globalPos())

    def menu(self) -> QMenu:
        m = QMenu(self)
        for s in STYLES:
            a = m.addAction(STYLE_NAMES[s])
            a.setCheckable(True)
            a.setChecked(s == self.style)
            a.triggered.connect(lambda _c, s=s: self.set_pref("sMeterStyle", s))
        m.addSeparator()
        for u in self.units():
            a = m.addAction(UNIT_NAMES[u])
            a.setCheckable(True)
            a.setChecked(u == self.unit)
            a.triggered.connect(lambda _c, u=u: self.set_pref("sMeterUnit", u))
        m.addSeparator()
        a = m.addAction(self.tr("Peak-hold needle"))
        a.setCheckable(True)
        a.setChecked(bool(self.prefs.get("sMeterPeak", True)))
        a.triggered.connect(lambda on: self.set_pref("sMeterPeak", bool(on)))
        m.addAction(self.tr("Calibrate…")).triggered.connect(self.open_calibrate)
        if self.cal.stored is not None:
            m.addAction(self.tr("Forget this calibration")).triggered.connect(
                lambda: self.set_pref("sMeterCal", forget(self.prefs.get("sMeterCal") or {}, self._st())))
        return m

    def open_calibrate(self):
        CalibrateDialog(self, self.window()).exec()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _e):
        self.paints += 1
        p = QPainter(self)
        style = self.style
        if style == "analog":
            self._paint_analog(p)
        elif style == "digital":
            self._paint_digital(p)
        else:
            self.paint_bar(p)
            self._paint_uncal(p, 0)

    def _paint_uncal(self, p: QPainter, y: float):
        """The UNCAL chip after the label: S-units or dBm with no calibration
        that holds. Its reason is the tooltip."""
        if not self.rd.uncal:
            return
        p.setFont(theme.caps(10))
        x = QFontMetricsF(p.font()).horizontalAdvance(self.label) + 8
        f = theme.caps(8.5)
        uncal = self.tr("UNCAL")
        tw = QFontMetricsF(f).horizontalAdvance(uncal) + 10
        r = QRectF(x, y + 2, tw, 13)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("warn", 0.18))
        p.drawRoundedRect(r, 3, 3)
        p.setFont(f)
        p.setPen(theme.c("warn"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, uncal)

    def _header(self, p: QPainter, right: str):
        w = self.width()
        on = self.active and self.rd.value is not None
        p.setFont(theme.caps(10))
        p.setPen(theme.c("text3"))
        p.drawText(QRectF(0, 0, w * 0.6, 16), Qt.AlignmentFlag.AlignVCenter, self.label)
        p.setFont(theme.font(13, theme.QFont.Weight.DemiBold, mono=True))
        p.setPen(theme.c("text") if on else theme.c("text3"))
        p.drawText(QRectF(w * 0.3, 0, w * 0.7, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)
        self._paint_uncal(p, 0)

    # -- analogue
    def _geom(self, w: float, h: float):
        """(face rect, pivot x, pivot y, scale radius): the arc as wide as the
        face allows and no deeper than leaves the needle room to show."""
        face = QRectF(0.5, 20.5, w - 1, h - 21)
        shroud = 16.0
        r_lab = min((w / 2 - 14) / math.sin(math.radians(HALF_SWEEP)),
                    (face.height() - 14 - shroud - 24) / (1 - math.cos(math.radians(HALF_SWEEP))))
        cy = face.top() + 14 + r_lab
        return face, w / 2, cy, r_lab - 12

    def _face_pixmaps(self, w: int, h: int):
        dpr = self.devicePixelRatioF()
        key = (w, h, dpr, theme.t()["name"], self.shown, self._s9, self.rd.uncal, self.on_air)
        if self._face is not None and self._face[0] == key:
            return self._face[1], self._face[2]
        face_pm = QPixmap(int(w * dpr), int(h * dpr))
        face_pm.setDevicePixelRatio(dpr)
        face_pm.fill(Qt.GlobalColor.transparent)
        glass_pm = QPixmap(int(w * dpr), int(h * dpr))
        glass_pm.setDevicePixelRatio(dpr)
        glass_pm.fill(Qt.GlobalColor.transparent)
        self._draw_face(QPainter(face_pm), w, h)
        self._draw_glass(QPainter(glass_pm), w, h)
        self._face = (key, face_pm, glass_pm)
        return face_pm, glass_pm

    def _draw_face(self, p: QPainter, w: float, h: float):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        face, cx, cy, R = self._geom(w, h)
        light = theme.t()["name"] == "light"
        # A warm, faintly backlit face in the light theme (an old rig's
        # cream dial); in the dark one an instrument face tinted by the RX
        # colour, so the meter belongs to the same panel as the scopes.
        top = mix(theme.c("bg1"), theme.c("own"), 0.10) if light else mix(theme.c("bg2"), theme.c("rx"), 0.06)
        bot = mix(theme.c("bg2"), theme.c("own"), 0.16) if light else theme.c("bg0")
        g = QLinearGradient(0, face.top(), 0, face.bottom())
        g.setColorAt(0, top)
        g.setColorAt(1, bot)
        p.setPen(QPen(theme.c("line2"), 1))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(face, 7, 7)
        glow = QRadialGradient(QPointF(cx, face.top() + face.height() * 0.55), face.width() * 0.55)
        glow.setColorAt(0, theme.c("own" if light else "rx", 0.10 if light else 0.07))
        glow.setColorAt(1, theme.c("own" if light else "rx", 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawRoundedRect(face, 7, 7)
        sc = self.scale
        ink = theme.c("text2")

        def pt(v, r):
            a = math.radians(needle_angle(sc.pos(v)))
            return QPointF(cx + r * math.sin(a), cy - r * math.cos(a))

        def arc(a_v, b_v, r, pen):
            a0, a1 = needle_angle(sc.pos(a_v)), needle_angle(sc.pos(b_v))
            rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Qt's arcs run anticlockwise from 3 o'clock, in 1/16 degree.
            p.drawArc(rect, int((90 - a0) * 16), int(-(a1 - a0) * 16))

        # The coloured band just inside the scale line: the classic section
        # beyond S9 - red only on the air (module docstring), otherwise a
        # neutral ink band so the dial still shows where S9 is - and the
        # unit's own zones elsewhere.
        for a, z, k in sc.zones:
            k = self.zone_colour(k) if k != OVER or self.on_air else "text3"
            pen = QPen(theme.c(k, 0.85 if k in ("err", "warn") else 0.55), 4)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            arc(a, z, R - 3, pen)
        arc(sc.lo, sc.hi, R, QPen(ink, 1.2))
        f = theme.font(10.5, theme.QFont.Weight.DemiBold, mono=True)
        fm = QFontMetricsF(f)
        p.setFont(f)
        for v, lab, major in sc.ticks:
            hot = any(self.zone_colour(k) == "err" and a < v <= z for a, z, k in sc.zones)
            col = theme.c("err") if hot else ink
            p.setPen(QPen(col if major else theme.c("text3"), 1.4 if major else 1.0))
            p.drawLine(pt(v, R), pt(v, R - (9 if major else 5)))
            if lab:
                c = pt(v, R + 9)
                lw = fm.horizontalAdvance(lab)
                p.setPen(col)
                p.drawText(QRectF(c.x() - lw / 2 - 1, c.y() - 7, lw + 2, 14), Qt.AlignmentFlag.AlignCenter, lab)
        p.end()

    def legend_layout(self, w: float, h: float) -> list[tuple[QRectF, str, str, object, Qt.AlignmentFlag]]:
        """(box, text, colour token, font, alignment) for each piece of the
        dial's legend: the unit on the left of the shroud, the S9 rule (and
        UNCAL) on the right, either side of the pivot's cap.

        On the shroud, not on the face. It used to sit in the middle of the
        face, above the pivot, which is exactly where the needle sweeps: every
        reading near mid-scale crossed "S units" and the S9 line (0.1.3
        screenshots). Nothing on the face between the pivot and the scale can
        escape a needle that pivots below it, and the corners outside the
        sweep are too small on a narrow rail for "dB over noise". The shroud
        is painted over the needle, so text on it is never crossed at any
        reading, by the needle or by the peak needle - a meter maker's
        printed bezel."""
        face, cx, _cy, _R = self._geom(w, h)
        sh = QRectF(face.left(), face.bottom() - 16, face.width(), 16)
        cap = 13.0                                   # clear of the pivot's cap (9 px) with a margin
        left = QRectF(sh.left() + 10, sh.top() + 1, cx - cap - sh.left() - 10, sh.height() - 1)
        right = QRectF(cx + cap, sh.top() + 1, sh.right() - 10 - cx - cap, sh.height() - 1)
        out = []
        # Units are spelt as units (dBm, not DBM), so no small capitals here.
        f = theme.font(9.5, theme.QFont.Weight.DemiBold, spacing=1.0)
        leg = {"s": "S units", "dbm": "dBm", "dbfs": "dBFS", "snr": "dB over noise", "beacon": "dB vs beacon",
               "sbeacon": "S (beacon ref)"}[self.shown]
        if QFontMetricsF(f).horizontalAdvance(leg) <= left.width():
            out.append((left, leg, "text3", f, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
        if self.shown == "sbeacon":
            f = theme.font(8.5, mono=True)
            a = self.tr("S9 = beacon")
            if QFontMetricsF(f).horizontalAdvance(a) <= right.width():
                out.append((right, a, "text3", f, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        if self.shown in ("s", "dbm"):
            f = theme.font(8.5, mono=True)
            fm = QFontMetricsF(f)
            band = "HF" if self._s9 == S9_HF_DBM else "VHF+"
            # Longest that fits; the header's UNCAL chip says it too, so it
            # is the first to go on a narrow rail, then the band.
            for a in (f"S9 {self._s9:.0f} dBm · {band}", f"S9 {self._s9:.0f} dBm"):
                b = " · UNCAL" if self.rd.uncal else ""
                if b and fm.horizontalAdvance(a + b) > right.width():
                    b = ""
                if fm.horizontalAdvance(a + b) <= right.width():
                    wa, wb = fm.horizontalAdvance(a), fm.horizontalAdvance(b)
                    x = right.right() - wa - wb
                    out.append((QRectF(x, right.top(), wa, right.height()), a, "text3", f,
                                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
                    if b:
                        out.append((QRectF(x + wa, right.top(), wb, right.height()), b, "warn", f,
                                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
                    break
        return out

    def _draw_glass(self, p: QPainter, w: float, h: float):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        face, cx, cy, R = self._geom(w, h)
        clip = QPainterPath()
        clip.addRoundedRect(face, 7, 7)
        p.setClipPath(clip)
        # The shroud the needle's pivot hides behind.
        sh = QRectF(face.left(), face.bottom() - 16, face.width(), 16)
        g = QLinearGradient(0, sh.top(), 0, sh.bottom())
        g.setColorAt(0, theme.c("bg3"))
        g.setColorAt(1, theme.c("bg2"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRect(sh)
        p.setPen(QPen(theme.c("line2"), 1))
        p.drawLine(QPointF(sh.left(), sh.top()), QPointF(sh.right(), sh.top()))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("line2"))
        p.drawEllipse(QPointF(cx, sh.top() + 1), 9, 5)
        for box, text, col, font, align in self.legend_layout(w, h):
            p.setFont(font)
            p.setPen(theme.c(col))
            p.drawText(box, align, text)
        p.setPen(Qt.PenStyle.NoPen)
        # Glare across the top of the glass.
        light = theme.t()["name"] == "light"
        gl = QPainterPath()
        gl.moveTo(face.left(), face.top())
        gl.lineTo(face.right(), face.top())
        gl.lineTo(face.right(), face.top() + face.height() * 0.22)
        gl.quadTo(cx, face.top() + face.height() * 0.48, face.left(), face.top() + face.height() * 0.30)
        gl.closeSubpath()
        g = QLinearGradient(0, face.top(), 0, face.top() + face.height() * 0.45)
        g.setColorAt(0, QColor(255, 255, 255, 70 if light else 22))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(g))
        p.drawPath(gl)
        p.end()

    def _needle(self, p: QPainter, cx, cy, R, pos, colour: QColor, width: float, shadow: bool):
        a = math.radians(needle_angle(pos))
        s, c = math.sin(a), math.cos(a)
        tip = QPointF(cx + (R + 3) * s, cy - (R + 3) * c)
        base = QPointF(cx + R * 0.35 * s, cy - R * 0.35 * c)
        if shadow:
            pen = QPen(theme.c("shadow", 0.28), width + 1)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(base + QPointF(2, 2), tip + QPointF(2, 2))
        pen = QPen(colour, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(base, tip)

    def _paint_analog(self, p: QPainter):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        self._header(p, self.value_text())
        face_pm, glass_pm = self._face_pixmaps(w, h)
        p.drawPixmap(0, 0, face_pm)
        face, cx, cy, R = self._geom(w, h)
        clip = QPainterPath()
        clip.addRoundedRect(face, 7, 7)
        p.save()
        p.setClipPath(clip)
        # The needles end at the shroud: it hides them, but its bottom edge
        # is half a pixel of antialiasing that let a needle show through
        # under the legend printed on it.
        p.setClipRect(QRectF(face.left(), face.top(), face.width(), face.height() - 15),
                      Qt.ClipOperation.IntersectClip)
        on = self.active and self.b.valid
        if on and self.prefs.get("sMeterPeak", True) and self.b.peak > self.b.value + 0.004:
            self._needle(p, cx, cy, R, self.b.peak, theme.c("warn", 0.75), 1.2, False)
        # The needle in the text colour - ink on the light face, lit on the
        # dark - because a red one vanishes over the red beyond S9.
        self._needle(p, cx, cy, R, self.b.value, theme.c("text") if on else theme.c("text3"), 2.0, True)
        p.restore()
        p.drawPixmap(0, 0, glass_pm)

    # -- digital
    def _paint_digital(self, p: QPainter):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        on = self.active and self.rd.value is not None
        p.setFont(theme.caps(10))
        p.setPen(theme.c("text3"))
        p.drawText(QRectF(0, 0, w * 0.6, 16), Qt.AlignmentFlag.AlignVCenter, self.label)
        self._paint_uncal(p, 0)
        p.setFont(theme.font(10.5, theme.QFont.Weight.DemiBold, spacing=0.6))
        p.setPen(theme.c("accent"))
        p.drawText(self.unit_rect().adjusted(0, 0, 0, -2), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   UNIT_NAMES[self.shown] + " ▸")
        big = theme.font(30, theme.QFont.Weight.Bold, mono=True)
        p.setFont(big)
        txt = self.rd.text if on else "—"
        r = QRectF(0, 15, w, 38)
        # Unlit segments behind the figures: an LCD's ghost, in the same
        # fixed-width cells, so the readout reads as a display, not a label.
        ghost = re.sub(r"[0-9]", "8", txt)
        p.setPen(theme.c("text3", 0.13))
        p.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, ghost)
        col = theme.c("text3")
        if on:
            col = theme.c("text")
            pos = self.scale.pos(self.rd.value)
            for a, z, k in self.zones:
                if a <= pos <= z and k in ("err", "warn"):
                    col = theme.c(k)
        p.setPen(col)
        p.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, txt)
        if on and self.rd.second:
            p.setFont(theme.font(12, mono=True))
            p.setPen(theme.c("text3"))
            p.drawText(QRectF(0, 22, w, 30), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, self.rd.second)
        tr = QRectF(0, h - 7, w, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("bg3"))
        p.drawRoundedRect(tr, 2, 2)
        if self.active and self.b.valid:
            g = QLinearGradient(tr.x(), 0, tr.right(), 0)
            for a, z, k in self.zones:
                g.setColorAt(max(0.0, min(1.0, a)), theme.c(k))
                g.setColorAt(max(0.0, min(1.0, z)), theme.c(k))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(QRectF(tr.x(), tr.y(), max(2.0, self.b.value * tr.width()), tr.height()), 2, 2)
            p.setBrush(theme.c("text"))
            p.drawRect(QRectF(tr.x() + self.b.peak * tr.width() - 1, tr.y() - 2, 2, tr.height() + 4))


# ------------------------------------------------------------- Calibrate…
class CalibrateDialog(QDialog):
    """Enter the known level of the signal in the passband; the offset is
    whatever makes the meter's average of the last three seconds read it."""

    def __init__(self, meter: SMeter, parent=None):
        super().__init__(parent)
        from .controls import Button
        self.meter = meter
        self.setWindowTitle(self.tr("Calibrate the S-meter"))
        self.setModal(True)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(8)
        h = QLabel(self.tr("Calibrate the S-meter"))
        h.setFont(theme.font(18, theme.QFont.Weight.Bold))
        lay.addWidget(h)
        # Two whole sentences, with and without the band, rather than the
        # band's clause spliced into the middle of one.
        if meter._st().get("band") is not None:
            intro = QLabel(self.tr(
                "Put a signal of known level in the receive passband - best, a signal generator through a known "
                "attenuator into the antenna socket - and type its level. The meter is set to read it, for this "
                "radio on this band at this receiver gain; a later manual gain change is allowed for."))
        else:
            intro = QLabel(self.tr(
                "Put a signal of known level in the receive passband - best, a signal generator through a known "
                "attenuator into the antenna socket - and type its level. The meter is set to read it, for this "
                "radio at this receiver gain; a later manual gain change is allowed for."))
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        lay.addWidget(intro)
        self.where = QLabel("")
        self.where.setWordWrap(True)
        lay.addWidget(self.where)
        self.now = QLabel("")
        self.now.setFont(theme.font(13, mono=True))
        lay.addWidget(self.now)
        cap = QLabel(self.tr("Known level"))
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        self.level = QLineEdit()
        self.level.setPlaceholderText(self.tr("-73 dBm, S9, S9+20 or 50 uV"))
        self.level.textChanged.connect(self._preview)
        lay.addWidget(self.level)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        if meter.cal.stored is not None:
            fg = Button(self.tr("Forget this calibration"), kind="ghost")
            fg.clicked.connect(self.forget)
            row.addWidget(fg)
        row.addStretch(1)
        cancel = Button(self.tr("Cancel"), kind="ghost")
        cancel.clicked.connect(self.reject)
        self.ok = Button(self.tr("Calibrate"), kind="primary")
        self.ok.clicked.connect(self.apply)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._preview)
        self.timer.start()
        self._preview()

    def _compute(self):
        """(new store, sentence) or raises ValueError."""
        st = self.meter._st()
        avg = self.meter.average_dbfs()
        if not self.level.text().strip():
            raise ValueError("")
        known = parse_level(self.level.text(), s9_dbm(st.get("vfo", 0.0)))
        store = calibrate(self.meter.prefs.get("sMeterCal") or {}, st, avg[0] if avg else None, known)
        off = store[cal_key(st)]["offset"]
        return store, self.tr("Offset {offset} dB: this signal will read {reading} ({dbm} dBm).").format(
            offset=f"{off:+.1f}", reading=s_text(known, s9_dbm(st.get('vfo', 0))), dbm=f"{known:.1f}")

    def _preview(self):
        st = self.meter._st()
        g = known_gain(st)
        # One whole line per case (band or none, gain known or AGC), not
        # three pieces joined.
        band = st.get("band")
        if band and g is not None:
            where = self.tr("Radio: {radio} · {band} · receiver gain {gain} dB")
        elif band:
            where = self.tr("Radio: {radio} · {band} · receiver gain: AGC (unknown)")
        elif g is not None:
            where = self.tr("Radio: {radio} · receiver gain {gain} dB")
        else:
            where = self.tr("Radio: {radio} · receiver gain: AGC (unknown)")
        self.where.setText(where.format(radio=device_key(st), band=band, gain="" if g is None else f"{g:g}"))
        avg = self.meter.average_dbfs()
        self.now.setText(self.tr("Measured now: {level} dBFS (3 s average, ±{spread} dB)").format(
                         level=f"{avg[0]:.1f}", spread=f"{avg[1]:.1f}") if avg
                         else self.tr("Measured now: no reading"))
        try:
            _store, sentence = self._compute()
            self.msg.setStyleSheet(f"color: {theme.t()['text2']};")
            self.msg.setText(sentence)
            self.ok.setEnabled(True)
        except ValueError as e:
            self.msg.setStyleSheet(f"color: {theme.t()['warn']};")
            self.msg.setText(str(e))
            self.ok.setEnabled(False)

    def apply(self):
        try:
            store, _ = self._compute()
        except ValueError as e:
            self.msg.setText(str(e))
            return
        self.meter.set_pref("sMeterCal", store)
        self.accept()

    def forget(self):
        self.meter.set_pref("sMeterCal", forget(self.meter.prefs.get("sMeterCal") or {}, self.meter._st()))
        self.accept()

    def done(self, r):
        self.timer.stop()
        super().done(r)


# ------------------------------------------------------------- Settings
def settings_section(dlg, lay):
    """The S-meter's part of Settings › Radio: style, unit, the peak needle,
    and this radio's calibration. Saved by store_settings()."""
    from .controls import Button, Segmented, Toggle
    prefs = dlg.prefs
    dlg._section(lay, QCoreApplication.translate("SMeter", "S-meter"))
    beacon = bool(getattr(dlg.bridge.face, "smeter_beacon", False))
    cap = QLabel(QCoreApplication.translate("SMeter", "Style"))
    cap.setObjectName("Muted")
    lay.addWidget(cap)
    style = Segmented([(s, STYLE_NAMES[s]) for s in STYLES], prefs.get("sMeterStyle", "bar"))
    lay.addWidget(style)
    cap = QLabel(QCoreApplication.translate("SMeter", "Units"))
    cap.setObjectName("Muted")
    lay.addWidget(cap)
    units = [u for u in UNITS if u not in BEACON_UNITS or beacon]
    default = str(getattr(dlg.bridge.face, "smeter_default_unit", "dbfs"))
    short = {"snr": QCoreApplication.translate("SMeter", "Over noise"),
             "beacon": QCoreApplication.translate("SMeter", "vs beacon"),
             "sbeacon": QCoreApplication.translate("SMeter", "S (beacon)")}
    unit = Segmented([(u, short.get(u, UNIT_NAMES[u])) for u in units],
                     resolve_unit(prefs.get("sMeterUnit", ""), tuple(units), default))
    lay.addWidget(unit)
    peak = Toggle(QCoreApplication.translate("SMeter", "Peak-hold needle (analogue)"),
                  bool(prefs.get("sMeterPeak", True)))
    lay.addWidget(peak)
    st = dlg.st
    cal = effective(prefs.get("sMeterCal") or {}, st)
    cap = QLabel(QCoreApplication.translate("SMeter", "Calibration offset for {radio}").format(radio=where_text(st)))
    cap.setObjectName("Muted")
    lay.addWidget(cap)
    off = QLineEdit("" if cal.stored is None else f"{cal.offset:.2f}")
    off.setPlaceholderText(QCoreApplication.translate("SMeter", "not calibrated"))
    lay.addWidget(off)
    note = QLabel(cal.why.replace(_calibrate_hint(), "").strip() + " " + QCoreApplication.translate(
                  "SMeter", "The offset is what is added to the dBFS reading to give dBm, at the receiver gain set "
                  "now; empty is uncalibrated. Calibrate… measures it from a signal of known level. Until a calibration "
                  "holds, S-units and dBm show UNCAL and a relative reading instead of an absolute one."))
    note.setWordWrap(True)
    note.setObjectName("Faint")
    note.setFont(theme.font(12))
    lay.addWidget(note)
    row = QHBoxLayout()
    btn = Button(QCoreApplication.translate("SMeter", "Calibrate…"), small=True)
    meter = getattr(getattr(dlg.parent(), "rxcard", None), "s", None)
    btn.setEnabled(isinstance(meter, SMeter))

    def run():
        CalibrateDialog(meter, dlg).exec()
        c = effective(meter.prefs.get("sMeterCal") or {}, st)
        off.setText("" if c.stored is None else f"{c.offset:.2f}")
        dlg._smeter["before"] = off.text()
    btn.clicked.connect(run)
    row.addWidget(btn)
    row.addStretch(1)
    lay.addLayout(row)
    dlg._smeter = {"style": style, "unit": unit, "peak": peak, "offset": off, "before": off.text()}


def read_settings(dlg) -> dict | None:
    """The section's values, checked before anything is saved; ValueError
    with a sentence if the offset will not do."""
    w = getattr(dlg, "_smeter", None)
    if w is None:
        return None
    out = {"sMeterStyle": w["style"].value, "sMeterUnit": w["unit"].value, "sMeterPeak": w["peak"].on}
    text = w["offset"].text().strip().replace(",", ".").replace("−", "-")
    if text != w["before"]:
        store = dlg.prefs.get("sMeterCal") or {}
        if not text:
            out["sMeterCal"] = forget(store, dlg.st)
        else:
            try:
                v = float(text.split()[0])
            except ValueError:
                raise ValueError(QCoreApplication.translate("SMeter", "S-meter calibration offset: not a number")) \
                    from None
            if not -250 <= v <= 250:
                raise ValueError(QCoreApplication.translate("SMeter",
                                                            "S-meter calibration offset: outside -250..+250 dB"))
            key, g = cal_key(dlg.st), known_gain(dlg.st)
            if key is None or g is None:
                raise ValueError(QCoreApplication.translate("SMeter", "S-meter calibration offset: {reason}")
                                 .format(reason=effective(store, dlg.st).why))
            store = clean_cal(store)
            store[key] = {"offset": v, "gain": g, "when": time.strftime("%Y-%m-%d")}
            out["sMeterCal"] = store
    return out


def store_settings(prefs, values: dict | None):
    if values:
        for k, v in values.items():
            prefs[k] = v
