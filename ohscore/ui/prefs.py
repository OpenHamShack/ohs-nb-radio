"""Preferences that belong to the window, not the radio.

The engine's config (the app's state registry) holds everything that
decides what the radio does. What is left - theme, palette, each scope's
scale, peaks and waterfall levels, macros, the second display, window
geometry, and whether the operator has acknowledged the licence
conditions - lives here, in `ui.json` beside the engine's config,
so the engine never learns about windows.

The licence acknowledgement is deliberately a UI matter: it gates the PTT
button and the send buttons, which are the UI's only ways to key. A missing
or unreadable file means "not acknowledged", never the reverse.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from pathlib import Path

from ..config import Config
from .layoutrules import nearest_scale

log = logging.getLogger("ohscore.ui.prefs")

DEFAULTS = {
    "welcomed": False,
    "licenceAck": False,
    "theme": "dark",
    "palette": "Ember",
    "wfAuto": True,
    "wfFloor": -110.0,
    "wfRange": 50.0,
    "wfSpeed": 1.0,
    "zoomWfAuto": True,
    "zoomWfFloor": -120.0,
    "zoomWfRange": 50.0,
    # Each scope's trace (the adjust panel, ohscore/ui/wfpanel.py): "spec" is
    # the wide scope and the second display's, "zoomSpec" the zoom's.
    "specAuto": True,
    "specTop": -40.0,
    "specRange": 90.0,
    "zoomSpecAuto": True,
    "zoomSpecTop": -40.0,
    "zoomSpecRange": 70.0,
    # The peak ghost: on, hold seconds (-1: until cleared), fall dB/s. The
    # defaults are its look before it was adjustable.
    "specPeak": True,
    "specPeakHold": 1.5,
    "specPeakFall": 10.0,
    "zoomSpecPeak": True,
    "zoomSpecPeakHold": 1.5,
    "zoomSpecPeakFall": 10.0,
    # The drawn trace's averaging, a time constant in seconds (0: raw).
    # 0.13 s is the 0.32-per-line it always had, at 20 lines/s.
    "specSmooth": 0.13,
    "zoomSpecSmooth": 0.13,
    # Display style (ohscore/ui/scope.py DISPLAY_STYLES): "nb", the app's
    # own fine-bin look, or "sdrconsole", a wider RBW and a hang-and-decay
    # trace like SDR Console's. Display only; no reading changes with it.
    "specStyle": "nb",
    "zoomSpecStyle": "nb",
    # Peak markers: label the strongest signals; dB above the noise floor
    # to count, and how many at most. Off unless asked for.
    "specMarks": False,
    "specMarkAbove": 10.0,
    "specMarkMax": 5,
    "zoomSpecMarks": False,
    "zoomSpecMarkAbove": 10.0,
    "zoomSpecMarkMax": 5,
    "adjustTab": "waterfall",
    # Every scope's signal labels: decode labels, band marks, alert captions
    # (ohscore/ui/scope.py labels_shown; Adjust › Scope, or L).
    "scopeLabels": True,
    # How every scope's trace looks (Settings › Display, ohscore/ui/scopelook.py):
    # {} is Classic, the original look.
    "scopeLook": {},
    "secondDisplay": False,
    "secondScreen": "",
    "secondFullScreen": False,
    "secondContent": "waterfall",
    "geometry": "",
    "windowState": "",
    # The splitters' sizes in pixels, as the window kept them until the
    # October 2026 overhaul: {"split_main": [wide, lower], "split_low":
    # [zoom, panel], "split_side": [main, rail]}, and the same for FT8 and
    # FT4 in slotSplitters. Still written, so a downgrade finds its own;
    # read only to fill `workspaces` the first time (migrate()).
    "splitters": {},
    "slotSplitters": {},
    # The workspace (docs/ui-overhaul-2026-10.md section 2): "auto" follows
    # the mode (ohscore/modegroups.py workspace_for); "digital", "voice" or
    # "watch" is one the operator pinned.
    "workspace": "auto",
    # Per workspace, what the operator made of it: {"digital": {"wide":
    # 0.25, "zoom": 0.17, "rail": 320, "view": "mode", "expanded": [...]},
    # ...}. "wide" is the wide scope's share of the body's height, "zoom"
    # the zoom scope's share of the lower width (fractions, so a layout
    # dragged at 1920 x 1080 is the same layout full screen, on a laptop or
    # with larger text), "rail" its width in px, then the lower view last
    # shown and the rail cards expanded. A workspace not in here has never
    # been changed and uses its defaults; "Reset this workspace's layout"
    # removes its entry.
    "workspaces": {},
    # The modes last used, newest first (the compact mode buttons show each
    # group's most recent; the Ctrl+E menu lists them first).
    "modeRecent": [],
    # Settings › Display › Text size: 1.0, 1.15 or 1.3 (ohscore/ui/theme.py
    # set_scale; ohscore/ui/layoutrules.py TEXT_SCALES).
    "textScale": 1.0,
    "cwMacros": ["CQ CQ DE {MYCALL} {MYCALL} K", "{CALL} DE {MYCALL} UR {RST} {RST} BK", "TU 73 DE {MYCALL} SK",
                 "{CALL} DE {MYCALL}", "QRZ? DE {MYCALL}", "73 TU"],
    "textMacros": ["CQ CQ CQ de {MYCALL} {MYCALL} {MYCALL} pse k", "{CALL} de {MYCALL} - ur {RST} - btu",
                   "{CALL} de {MYCALL} - tnx QSO, 73 - {CALL} de {MYCALL} sk", "{MYCALL} {MYCALL} {MYCALL}"],
    "ft8TxOffset": 1500.0,
    "ft8RxOffset": 1500.0,
    "ft8AutoSeq": True,
    "ft8HoldTx": True,
    # TX = RX in the FT8 panel: transmit on the receive audio offset and
    # keep the two together (ohscore/ui/panels/ft8.py). Off, as WSJT-X starts.
    "ft8TxEqRx": False,
    # The band activity's text size in pixels (Ctrl and the wheel over it).
    # 16 since the UI overhaul (decision 11; 15 before): a size already
    # saved is kept, as for every key here.
    "ft8FontPx": 16.0,
    # The speed the JS8 panel sends at (ohscore/modegroups.py JS8_SPEEDS).
    "js8Speed": "normal",
    "textOffset": 1000.0,
    "showShortcutsHint": True,
    # The Receive card's S-meter (ohscore/ui/smeter.py): style, unit, the
    # analogue peak needle, and the calibrations, per radio (and band).
    "sMeterStyle": "bar",
    # "" = the app's own default (Face.smeter_default_unit); a stored choice
    # always beats it.
    "sMeterUnit": "",
    "sMeterPeak": True,
    "sMeterCal": {},
    # NB's multimedia beacon view (ohsnb/ui/mmbview.py): DX-cluster spots on
    # the wide scope, and which of its pages was last open.
    "mmbSpots": True,
    "mmbTab": "bulletins",
    # NB's band skimmer view (ohsnb/ui/skimview.py): its marks on the wide
    # scope, and which signals the list shows.
    "skimMarks": True,
    "skimFilter": "all",
    # Radio's CW Activity view (ohscore/ui/cwskimview.py): its marks on the
    # wide scope, which list was last open, and how the spots are sorted.
    "cwSkimMarks": True,
    "cwSkimTab": "spots",
    "cwSkimSort": "freq",
    # Whether the AKP03E controller pad may key the transmitter (K1 held is
    # PTT, through the lease: ohscore/ui/padlink.py). Off until the operator
    # says so in Settings › Control pad; like licenceAck, a missing or
    # unreadable file means "no", never the reverse.
    "padTransmit": False,
    # Automatic diagnostics upload (ohscore/diagupload.py): off by default,
    # Brian's decision of 12/10/2026. It sends only with the switch on AND a
    # consent stamp for the current consent text, which only Settings ›
    # Station writes when the operator turns the switch on; a window pref,
    # like padTransmit, so no remote client can turn it on.
    "diagUpload": False,
    "diagUploadConsent": "",
}


def path(config: Config) -> Path:
    """ui.json beside the app's config.json, unless $<ENV>_UI_CONF says
    otherwise (NB: $OHS_NB_UI_CONF, or the former $OHSNB_UI_CONF)."""
    env = config.app.getenv("UI_CONF")
    if env:
        return Path(env)
    return config.conf_path().with_name("ui.json")


class Prefs:
    def __init__(self, where: "Config | Path | str"):
        """`where` is the app's Config (its ui.json, as path() finds it) or
        an explicit file."""
        self.path = path(where) if isinstance(where, Config) else Path(where)
        self.d = copy.deepcopy(DEFAULTS)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k not in DEFAULTS:
                        continue
                    d = DEFAULTS[k]
                    if type(v) is type(d):
                        self.d[k] = copy.deepcopy(v)
                    elif isinstance(d, float) and isinstance(v, int) and not isinstance(v, bool):
                        self.d[k] = float(v)
                if "workspaces" not in raw:
                    migrate(self.d)
        except (OSError, ValueError):
            pass
        self._validate()
        self.saved = copy.deepcopy(self.d)

    def _validate(self):
        """Values of the right type but outside what the window can show
        (a hand-edited file, a later version's choice) fall back to the
        default rather than reaching a layout that was never checked."""
        d = self.d
        d["textScale"] = nearest_scale(d["textScale"])
        if d["workspace"] not in WORKSPACE_CHOICES:
            d["workspace"] = "auto"
        d["workspaces"] = {w: v for w, v in d["workspaces"].items() if w in WORKSPACES and isinstance(v, dict)}
        d["modeRecent"] = [m for m in d["modeRecent"] if isinstance(m, str)][:MODE_RECENT_MAX]

    def __getitem__(self, k):
        return self.d[k]

    def get(self, k, default=None):
        return self.d.get(k, default)

    def __setitem__(self, k, v):
        self.d[k] = v

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ui-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.d, f, indent=1)
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("could not save %s: %s", self.path, e)
            return   # losing a window preference is not worth stopping the radio for
        # The keys, not the values (macros hold callsigns and words the
        # operator may not want in a report). Where the window sits is
        # saved on every close and says nothing about a fault: DEBUG.
        changed = sorted(k for k in self.d if self.d[k] != self.saved.get(k))
        self.saved = copy.deepcopy(self.d)
        loud = [k for k in changed if k not in QUIET]
        if loud:
            log.info("window preferences saved: %s changed", ", ".join(loud))
        elif changed:
            log.debug("window preferences saved: %s changed", ", ".join(changed))


# Saved on every close and every drag, and say nothing about a fault.
QUIET = ("geometry", "windowState", "splitters", "slotSplitters", "workspaces", "modeRecent")

WORKSPACES = ("digital", "voice", "watch")
WORKSPACE_CHOICES = ("auto", *WORKSPACES)
MODE_RECENT_MAX = 16
SPLITTER_NAMES = ("split_main", "split_low", "split_side")


def layout_from_sizes(sizes: dict) -> dict:
    """A workspace's layout ({"wide", "zoom", "rail"}, see DEFAULTS
    "workspaces") from splitter sizes in pixels as the window has them
    ({"split_main": [wide, lower], ...}). What cannot be read is left out,
    so the workspace's default fills it."""
    out = {}
    for name, key in (("split_main", "wide"), ("split_low", "zoom")):
        v = sizes.get(name) if isinstance(sizes, dict) else None
        if _pair(v) and v[0] + v[1] > 0:
            out[key] = v[0] / (v[0] + v[1])
    v = sizes.get("split_side") if isinstance(sizes, dict) else None
    if _pair(v):
        out["rail"] = int(v[1])
    return out


def sizes_from_layout(layout: dict, totals: dict) -> dict:
    """The inverse: pixel sizes for each splitter whose share or width the
    layout holds, given each splitter's total length now ({"split_main":
    body height, "split_low": lower width, "split_side": window width})."""
    out = {}
    for name, key in (("split_main", "wide"), ("split_low", "zoom")):
        f, t = layout.get(key), totals.get(name)
        if isinstance(f, (int, float)) and not isinstance(f, bool) and 0.0 <= f <= 1.0 and t:
            a = int(round(t * f))
            out[name] = [a, int(t) - a]
    r, t = layout.get("rail"), totals.get("split_side")
    if isinstance(r, int) and not isinstance(r, bool) and r > 0 and t:
        r = min(r, int(t))
        out["split_side"] = [int(t) - r, r]
    return out


def _pair(v) -> bool:
    return (isinstance(v, list) and len(v) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in v))


def migrate(d: dict) -> None:
    """The first load of a ui.json written before workspaces: the sizes the
    operator dragged for most modes become Voice's layout, FT8 and FT4's
    Digital's. Fractions of the sizes themselves: they were saved with the
    window's geometry, so they add up to the window as it was, and at that
    geometry the fractions give the same pixels back (within the rounding
    of a pixel). The old keys are left as they are."""
    ws = {}
    for old, new in (("splitters", "voice"), ("slotSplitters", "digital")):
        lay = layout_from_sizes(d.get(old) or {})
        if lay:
            ws[new] = lay
    d["workspaces"] = ws


# The fields a CW or keyboard macro (a "CW memory": F1 ... F8) may hold.
# {DXCALL} is {CALL} by its contest-logger name - the QSO box's "their
# call", the station being worked; {LOC} is the operator's own locator.
MACRO_FIELDS = ("{MYCALL}", "{CALL}", "{DXCALL}", "{RST}", "{LOC}")


def expand_macro(text: str, mycall: str, call: str = "", rst: str = "599", loc: str = "") -> str:
    return (text.replace("{MYCALL}", mycall or "NOCALL").replace("{DXCALL}", call or "").replace("{CALL}", call or "")
            .replace("{RST}", rst or "599").replace("{LOC}", loc or ""))


def macro_missing(text: str, mycall: str, call: str = "", loc: str = "") -> str:
    """'' if every field `text` uses has something to fill it, else the
    sentence saying what to fill in first. Sending "TU DE  K" because the
    QSO box was empty puts a malformed over on the air; until 0.1.10 the
    macro went anyway, with the call left out (or NOCALL for the
    operator's own)."""
    if ("{CALL}" in text or "{DXCALL}" in text) and not call:
        return "Type their call in the QSO box first: this macro sends it"
    if "{MYCALL}" in text and not mycall:
        return "Set your callsign first (Settings › Station): this macro sends it"
    if "{LOC}" in text and not loc:
        return "Set your locator first (Settings › Station): this macro sends it"
    return ""
