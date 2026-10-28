"""OpenHamShack Radio's answers to the shared widgets (ohscore/ui/face.py): the
amateur bands, 1.8 MHz to 5.85 GHz, as the scope, the readout, the
logbook and the voice panel show them.

Unlike NB's transponder, the band under the dial changes, so several
answers read the bridge's state (`self.st`, set when the window is
built): the wide scope's extent is the span the engine reports
(spanLo/spanHi), the readout's title names the band, and its digits are
grouped by the size of the number - "7.074 000", "145.500 000",
"1 296.200 000" - with the hundreds-of-hertz group small, as on NB.
"""
from __future__ import annotations

import re

from ohscore import update
from ohscore.dsp.fm import tone_name
from ohscore.ui.face import Face
from ohsradio.i18n import _

from .. import bands
from .. import plans

SHORT = {"CW": "CW", "CW & MGM": "CW/MGM", "narrow digital": "NARROW", "narrow digital (200 Hz)": "NARROW",
         "all modes": "ALL MODES", "all modes, no digital": "NO DIGI", "all modes, no SSB": "NO SSB",
         "IBP beacons": "IBP", "beacons": "BCN", "satellites": "SAT", "FM simplex": "FM", "FM calling": "FM",
         "repeater outputs": "RPT OUT", "repeater inputs": "RPT IN", "low-power repeater inputs": "LP IN",
         "repeater outputs (RU)": "RU OUT", "repeater outputs (RB)": "RB OUT", "repeater inputs (RB)": "RB IN",
         "repeater inputs (RU)": "RU IN", "repeater outputs (RM)": "RM OUT", "repeater inputs (RM)": "RM IN",
         "DV repeater inputs": "DV IN", "DV repeater outputs": "DV OUT", "SSB & MGM": "SSB/MGM",
         "narrow band": "NARROW", "FM channels": "FM", "FM & DV": "FM/DV", "60 m segment": "60 m"}
CLASS_WORD = {"cw": "cw", "ssb": "ssb", "am": "am", "fm": "fm", "digi": "digital", "dv": "dv", "image": "sstv"}


def mhz_text(hz: int) -> str:
    """'14.074 000', '1 296.200 000' - the readout's grouping as text."""
    mhz, rest = divmod(int(hz), 1_000_000)
    head = f"{mhz:,}".replace(",", " ")
    return f"{head}.{rest // 1000:03d} {rest % 1000:03d}"


def parse_freq(text: str) -> float:
    """A typed frequency -> Hz. "14.074" or "145.5" (MHz), "14074" or
    "1296174" (kHz), "14074000" (Hz), or anything with a unit (GHz, MHz,
    kHz, Hz). ValueError with a sentence."""
    s = text.strip().lower().replace(" ", "").replace(",", ".")
    m = re.fullmatch(r"([0-9.]+)(ghz|mhz|khz|hz|g|m|k)?", s)
    if not m or m.group(1).count(".") > 1:
        raise ValueError(_("{text} is not a frequency").format(text=repr(text)))
    x = float(m.group(1))
    unit = m.group(2)
    if unit in ("ghz", "g"):
        f = x * 1e9
    elif unit in ("mhz", "m"):
        f = x * 1e6
    elif unit in ("khz", "k"):
        f = x * 1e3
    elif unit == "hz":
        f = x
    elif x < 10_000:
        f = x * 1e6
    elif x < 10_000_000:
        f = x * 1e3
    else:
        f = x
    if not 100e3 <= f <= 6e9:
        raise ValueError(_("{mhz:.4f} MHz is outside what OpenHamShack Radio tunes (0.1 MHz - 6 GHz)").format(
            mhz=f / 1e6))
    return round(f)


class HamFace(Face):
    app_name = "OpenHamShack Radio"
    former_name = "OpenHamShack HAM"
    package = "openhamshack-radio"
    update_feed = "https://openhamshack.com/desktop/ham/update.json"
    update_feeds = update.with_mirrors(update_feed)
    # The app's name in a diagnostics upload (ohscore/diagupload.py), as in its feed's folder.
    diag_app = "ham"
    freq_label = "Frequency"
    freq_hint = "14.074, 145.5, 433500 or 1296.2"
    tx_width_limit = None
    axis_unit = "MHz"

    _TEXT = {"am": "AM transmits here: full carrier, modulation held under 90 %. The occupied width is twice "
                   "the audio's. AM is held 6 dB below full output, so its PEP at a given Drive is a quarter "
                   "of SSB's.",
             "txWidth": "",
             "licence": "I hold an amateur licence of the class set in Settings, valid where this station is, I "
                        "will transmit only within its terms, and I will not use the band simulator's numbers as my "
                        "power."}

    def __init__(self, bridge=None):
        self.bridge = bridge

    @property
    def st(self) -> dict:
        # The bridge replaces its st dict on (re)start, so it is read through
        # the bridge every time rather than held.
        return self.bridge.st if self.bridge is not None else {}

    def text(self, topic: str) -> str:
        return self._TEXT.get(topic, "")

    # ------------------------------------------------------------------ plan
    @property
    def plan(self):
        """The band plan in force (the engine's planInUse status: the
        station country's, or the operator's choice)."""
        return plans.get(self.st.get("planInUse") or plans.rsgb_2026.ID)

    @property
    def segments(self):
        p = self.plan
        if getattr(self, "_seg_plan", None) is not p:
            self._seg_plan = p
            self._segs = tuple((s.lo, s.hi, s.label, s.modes, s.max_bw or 0.0) for s in p.SEGMENTS)
        return self._segs

    @property
    def wide_lo(self) -> float:
        lo = float(self.st.get("spanLo") or 0.0)
        return lo if lo else float(self.st.get("vfo") or 145.5e6) - 500_000.0

    @property
    def wide_hi(self) -> float:
        hi = float(self.st.get("spanHi") or 0.0)
        return hi if hi else float(self.st.get("vfo") or 145.5e6) + 500_000.0

    def segment_at(self, f: float) -> dict | None:
        s = self.plan.segment_at(f)
        if s is None:
            return None
        return {"lo": s.lo, "hi": s.hi, "label": s.label, "tx": bool(s.modes) and not s.refused,
                "modes": sorted(CLASS_WORD.get(m, m) for m in (s.modes or ())), "maxBw": s.max_bw or 0.0}

    def short_label(self, label: str) -> str:
        return SHORT.get(label, label.upper())

    def markers(self) -> list[tuple[str, float, str]]:
        lo, hi = self.wide_lo, self.wide_hi
        out = [("ibp", f, "IBP") for f in self.plan.IBP if lo <= f <= hi]
        out += [(f"c{f}", float(f), lab) for f, lab, _m in self.plan.CENTRES
                if lo <= f <= hi and "calling" in lab]
        return out

    def mhz(self, f: float, places: int = 4) -> str:
        return f"{f / 1e6:.{places}f}"

    def axis_label(self, f: float, step: float) -> str:
        places = 1 if step >= 100_000 else 2 if step >= 10_000 else 3 if step >= 1_000 else 4
        return f"{f / 1e6:.{places}f}"

    # --------------------------------------------------------------- readout
    def readout_title(self) -> str:
        b = bands.BY_NAME.get(self.st.get("band", ""))
        name = b.name.replace("m", " m").replace("c m", " cm") if b else "Frequency"
        return f"{name} · MHz"

    def dial_label(self, st: dict) -> str:
        return (st.get("dialLabel") or {}).get("text", "")

    dial_label_keys = ("dialLabel",)

    def digit_groups(self, hz: int) -> list[tuple[str, int | None, str]]:
        hz = max(0, int(hz))
        mhz, rest = divmod(hz, 1_000_000)
        khz, h = divmod(rest, 1000)
        digits = str(mhz)
        out: list[tuple[str, int | None, str]] = []
        if len(digits) > 3:                                   # GHz: "1 296"
            out += [(digits[:-3], len(digits) + 5, "bright"), (" ", None, "gap"), (digits[-3:], 8, "bright")]
        else:
            out.append((digits, len(digits) + 5, "bright"))
        out += [(".", None, "dot"), (f"{khz:03d}", 5, "bright"), (" ", None, "gapS"), (f"{h:03d}", 2, "small")]
        return out

    def tunable_place(self, place: int) -> bool:
        return place <= 8

    def secondary(self, st: dict) -> tuple[str, str] | None:
        vfo = float(st.get("vfo") or 0.0)
        txd = float(st.get("txDial") or vfo)
        rxd = float(st.get("rxDial") or vfo)
        if st.get("mode") == "fm" and st.get("rptReverse"):
            return "RX", f"{mhz_text(int(round(rxd)))}  reverse"
        if abs(txd - vfo) >= 1:
            sh = float(st.get("shift") or 0.0)
            tail = f"  {sh / 1e6:+.3f}".replace("-", "−") if sh else ""
            return "TX", f"{mhz_text(int(round(txd)))}{tail}"
        if st.get("converter"):
            # Through a transverter: the frequency the radio itself is on.
            return "IF", f"{mhz_text(int(round(float(st.get('radioFreq') or 0.0))))}  {st['converter']}"
        return None

    def parse_freq(self, text: str) -> float:
        return parse_freq(text)

    # ---------------------------------------------------------------- other
    def icon(self):
        from .appicon import app_icon
        return app_icon()

    def big_freq(self, hz: int) -> str:
        return mhz_text(hz)

    def big_status(self, st: dict) -> tuple[str, str] | None:
        b = st.get("band") or ""
        mode = (st.get("mode") or "").upper()
        info = st.get("licenceInfo") or {}
        col = {"ok": "ok", "warn": "warn", "refused": "err"}.get(info.get("level"), "text3")
        extra = f" · {tone_name(st.get('ctcssTx') or 0)}" if st.get("mode") == "fm" and st.get("ctcssTx") else ""
        return f"{b} {mode}{extra}".strip(), col

    def panel(self, key: str, bridge, prefs, parent=None, big: bool = False):
        if key == "fm":
            from .fm import FmPanel
            return FmPanel(bridge, prefs, parent)
        return None
