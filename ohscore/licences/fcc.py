"""The United States amateur licence (FCC, 47 CFR Part 97): who may
transmit where, at what power.

Source: 47 CFR Part 97 as eCFR served it "as of" 2026-10-06 [F1], with the
binding allocation footnotes of 47 CFR 2.106 [F4], as transcribed in
docs/ham/countries/us.md (sections 3-6 and 8, each row citing its
paragraph). Part 97 was last amended with effect from 13 February 2026,
when 60 m was rewritten [F2]: anything about US 60 m from before that date
is wrong, and so is any copy of this module older than it.

Decisions, each because the alternative could let a transmitter key where
it may not:

- Classes are the five of 97.9(a). Novice and Advanced are kept: existing
  grants are renewed. The HF class boundaries are law (97.301(b)-(e)), not
  band-plan advice, so every one is a row of its own.
- The Region 2 column of 97.301 is the default. Where Region 3 differs (US
  territories in the Pacific: 75 m ends at 3900 kHz, 40 m at 7200 kHz,
  200 W PEP on 7050-7075 kHz, and no 1.25 m, 420-430 MHz, 440-450 MHz,
  33 cm or 5850-5925 MHz), the row carries `regions`. When the station's
  region is not known both sets apply and the tighter answer wins.
- Location rules are station conditions defaulting to the answer that
  refuses or limits (Line A, the US270 radar areas, the White Sands and
  Colorado/Wyoming boxes, Alaska near Russia), as are the 2200 m and 630 m
  notification to the Utilities Telecom Council.
- 3300-3450 MHz is not in Part 97: footnote US103 lets amateurs continue
  there but names no class or power, so it is refused, as us.md section 11
  recommends. 219-220 MHz (fixed digital message forwarding, after
  notifying ARRL and AMTS licensees) is refused too, as us.md section 3.2
  recommends.
- The 435-438 MHz Earth-station figure (611 W ERP / 1 kW EIRP) is shown as
  a note, not enforced: the 1500 W PEP of the row and the radar-area
  condition already hold the station at or below it.
- The ARRL plan's satellite segments (435-438, 145.8-146, 29.3-29.51 MHz)
  are band-plan matters, so they belong to the plan, not here.

QO-100 is below the horizon from every US state and territory (us.md
section 6), so the 13 cm satellite rows matter only generically: OpenHamShack
NB's uplink check gives Technician and up 2400-2450 MHz, and Novice nothing.
"""
from __future__ import annotations

from . import Limit

ID = "fcc-2026"
TITLE = "FCC Amateur Radio Service rules (47 CFR Part 97, as amended to 13 February 2026)"
SHORT = "United States (FCC)"
AUTHORITY = "FCC"
COUNTRY = ("US",)
PLAN = ""
# [F1] in docs/ham/countries/us.md.
SOURCE = {
    "title": "47 CFR Part 97, Amateur Radio Service (eCFR full part)",
    "url": "https://www.ecfr.gov/api/versioner/v1/full/2026-10-06/title-47.xml?part=97",
    "version": "eCFR point-in-time 2026-10-06; last amended by 91 FR 1405 (FCC 25-60), effective 13 Feb 2026",
    "date": "2026-02-13",
    "checked": "2026-10-08",
    "sha256": "7b86cd2b22f11437adc8720a19fd244529295a1f76728c214cb91b4e3c4583e3",
}
CLASSES = ("novice", "technician", "general", "advanced", "extra")
CLASS_NAME = {"novice": "Novice", "technician": "Technician", "general": "General", "advanced": "Advanced",
              "extra": "Amateur Extra"}

_P = "PEP"
R2, R3 = {"regions": (2,)}, {"regions": (3,)}


def _w(watts):
    return (float(watts), _P)


# Who holds what, by the letters of us.md's tables (N T G A E). The
# default is 1500 W PEP at the transmitter output (97.313(b)); Novice and
# Technician have 200 W PEP on their HF segments (97.313(c)(2)).
def _cls(letters, watts=1500.0, nt=None):
    names = {"N": "novice", "T": "technician", "G": "general", "A": "advanced", "E": "extra"}
    out = {}
    for ch in letters:
        if ch in "NT" and nt is not None:
            out[names[ch]] = _w(nt)
        else:
            out[names[ch]] = watts if isinstance(watts, tuple) else _w(watts)
    return out


def _k(lo_khz, hi_khz, lim, note, src, extras=None):
    row = (lo_khz * 1e3, hi_khz * 1e3, lim, note, src)
    return row + (extras,) if extras else row


def _m(lo_mhz, hi_mhz, lim, note, src, extras=None):
    return _k(lo_mhz * 1e3, hi_mhz * 1e3, lim, note, src, extras)


ALLOCATIONS = [
    # --- LF / MF / HF: us.md s.3.1. "PEP" is power supplied to the antenna
    # transmission line (97.3(b)(9)): the transmitter output.
    _k(135.7, 137.8, _cls("GAE", (Limit(1500.0, _P), Limit(1.0, "EIRP"))),
       "2200 m, secondary; 1500 W PEP and at most 1 W EIRP; fixed stations only, after notifying UTC",
       "47 CFR 97.301(b)-(d), 97.303(g), 97.313(k)"),
    _k(472, 479, _cls("GAE", (Limit(500.0, _P), Limit(5.0, "EIRP"))),
       "630 m, secondary; 500 W PEP and at most 5 W EIRP (1 W EIRP in Alaska within 800 km of Russia); fixed "
       "stations only, after notifying UTC", "47 CFR 97.301(b)-(d), 97.303(g), 97.313(l)"),
    _k(1800, 2000, _cls("GAE"), "160 m", "47 CFR 97.301(b)-(d)"),
    _k(3500, 3525, _cls("E"), "80 m, Extra only", "47 CFR 97.301(b)"),
    _k(3525, 3600, _cls("NTGAE", nt=200), "80 m; Novice and Technician CW only, 200 W PEP",
       "47 CFR 97.301(b)-(e), 97.307(f)(9), 97.313(c)(2)"),
    _k(3600, 3700, _cls("E"), "75 m, Extra only", "47 CFR 97.301(b)"),
    _k(3700, 3800, _cls("AE"), "75 m, Advanced and Extra", "47 CFR 97.301(b),(c)"),
    _k(3800, 3900, _cls("GAE"), "75 m", "47 CFR 97.301(b)-(d)"),
    _k(3900, 4000, _cls("GAE"), "75 m, Region 2 only (the Region 3 column ends at 3900 kHz)",
       "47 CFR 97.301(b)-(d)", R2),
    # 60 m is CHANNELLED below.
    _k(7000, 7025, _cls("E"), "40 m, Extra only", "47 CFR 97.301(b)"),
    _k(7025, 7050, _cls("NTGAE", nt=200), "40 m; Novice and Technician CW only, 200 W PEP",
       "47 CFR 97.301(b)-(e), 97.313(c)(2)"),
    _k(7050, 7075, _cls("NTGAE", nt=200), "40 m, Region 2; Novice and Technician CW only, 200 W PEP",
       "47 CFR 97.301(b)-(e), 97.313(c)(2)", R2),
    _k(7050, 7075, _cls("NTGAE", watts=200.0, nt=200),
       "40 m, Region 3: 200 W PEP for every class (97.313(c)(3)); Novice and Technician CW only",
       "47 CFR 97.301(b)-(e), 97.313(c)(2),(3)", R3),
    _k(7075, 7125, _cls("NTGAE", nt=200), "40 m; Novice and Technician CW only, 200 W PEP",
       "47 CFR 97.301(b)-(e), 97.313(c)(2)"),
    _k(7125, 7175, _cls("AE"), "40 m, Advanced and Extra", "47 CFR 97.301(b),(c)"),
    _k(7175, 7200, _cls("GAE"), "40 m", "47 CFR 97.301(b)-(d)"),
    _k(7200, 7300, _cls("GAE"), "40 m, Region 2 only; must accept broadcast interference",
       "47 CFR 97.301(b)-(d), 97.303(i)", R2),
    _k(10100, 10150, _cls("GAE", watts=200.0), "30 m, secondary; 200 W PEP",
       "47 CFR 97.301(b)-(d), 97.303(j), 97.313(c)(1)"),
    _k(14000, 14025, _cls("E"), "20 m, Extra only", "47 CFR 97.301(b)"),
    _k(14025, 14150, _cls("GAE"), "20 m", "47 CFR 97.301(b)-(d)"),
    _k(14150, 14175, _cls("E"), "20 m, Extra only", "47 CFR 97.301(b)"),
    _k(14175, 14225, _cls("AE"), "20 m, Advanced and Extra", "47 CFR 97.301(b),(c)"),
    _k(14225, 14350, _cls("GAE"), "20 m", "47 CFR 97.301(b)-(d)"),
    _k(18068, 18168, _cls("GAE"), "17 m", "47 CFR 97.301(b)-(d)"),
    _k(21000, 21025, _cls("E"), "15 m, Extra only", "47 CFR 97.301(b)"),
    _k(21025, 21200, _cls("NTGAE", nt=200), "15 m; Novice and Technician CW only, 200 W PEP",
       "47 CFR 97.301(b)-(e), 97.313(c)(2)"),
    _k(21200, 21225, _cls("E"), "15 m, Extra only", "47 CFR 97.301(b)"),
    _k(21225, 21275, _cls("AE"), "15 m, Advanced and Extra", "47 CFR 97.301(b),(c)"),
    _k(21275, 21450, _cls("GAE"), "15 m", "47 CFR 97.301(b)-(d)"),
    _k(24890, 24990, _cls("GAE"), "12 m", "47 CFR 97.301(b)-(d)"),
    _k(28000, 28500, _cls("NTGAE", nt=200), "10 m; Novice and Technician 200 W PEP",
       "47 CFR 97.301(b)-(e), 97.313(c)(2)"),
    _k(28500, 29700, _cls("GAE"), "10 m", "47 CFR 97.301(b)-(d)"),

    # --- VHF and up: 97.301(a), us.md s.3.2. Novice has only 222-225 and
    # 1270-1295 MHz from 97.301(e).
    _m(50, 54, _cls("TGAE"), "6 m", "47 CFR 97.301(a)"),
    _m(144, 148, _cls("TGAE"), "2 m; in Region 3, 146-148 MHz must accept interference",
       "47 CFR 97.301(a), 97.303(k)"),
    _m(222, 225, {**_cls("TGAE"), "novice": _w(25)}, "1.25 m, Region 2 only; Novice 25 W PEP",
       "47 CFR 97.301(a),(e), 97.313(d)", R2),
    _m(420, 430, _cls("TGAE"), "70 cm, Region 2 only; never north of Line A; 50 W PEP in US270 areas",
       "47 CFR 97.301(a), 97.303(m), 97.313(f)", R2),
    _m(430, 440, _cls("TGAE"), "70 cm, secondary; 50 W PEP in US270 areas",
       "47 CFR 97.301(a), 97.303(b),(d),(m), 97.313(f)"),
    _m(440, 450, _cls("TGAE"), "70 cm, Region 2 only; 50 W PEP in US270 areas",
       "47 CFR 97.301(a), 97.313(f)", R2),
    _m(902, 928, _cls("TGAE"), "33 cm, Region 2 only, secondary; not in the White Sands box; 50 W PEP within "
       "241 km of it; four slivers barred in the Colorado/Wyoming box",
       "47 CFR 97.301(a), 97.303(n), 97.313(g); 47 CFR 2.106 US275", R2),
    _m(1240, 1270, _cls("TGAE"), "23 cm, secondary", "47 CFR 97.301(a)"),
    _m(1270, 1295, {**_cls("TGAE"), "novice": _w(5)}, "23 cm, secondary; Novice 5 W PEP",
       "47 CFR 97.301(a),(e), 97.313(e)"),
    _m(1295, 1300, _cls("TGAE"), "23 cm, secondary", "47 CFR 97.301(a)"),
    _m(2300, 2310, _cls("TGAE"), "13 cm; 2305-2310 MHz secondary to WCS", "47 CFR 97.301(a), 97.303(p)"),
    _m(2390, 2400, _cls("TGAE"), "13 cm", "47 CFR 97.301(a), 97.303(p)"),
    _m(2400, 2450, _cls("TGAE"), "13 cm; must accept ISM interference; amateur-satellite (RR 5.282)",
       "47 CFR 97.301(a), 97.303(e)"),
    _m(5650, 5850, _cls("TGAE"), "5 cm; must accept ISM interference on 5725-5850 MHz",
       "47 CFR 97.301(a), 97.303(e),(r)"),
    _m(5850, 5925, _cls("TGAE"), "5 cm, Region 2 only; must accept FSS and ITS, and ISM interference on "
       "5850-5875 MHz", "47 CFR 97.301(a), 97.303(e),(r)", R2),
    _m(10000, 10500, _cls("TGAE"), "3 cm; pulse prohibited (US128)", "47 CFR 97.301(a); 47 CFR 2.106 US128"),
    _m(24000, 24250, _cls("TGAE"), "1.2 cm", "47 CFR 97.301(a)"),
    _m(47000, 47200, _cls("TGAE"), "6 mm", "47 CFR 97.301(a)"),
    _m(76000, 81000, _cls("TGAE", watts=(316.0, "EIRP")), "4 mm; 316 W peak EIRP", "47 CFR 97.301(a), 97.313(m)"),
    _m(122250, 123000, _cls("TGAE"), "2.5 mm", "47 CFR 97.301(a)"),
    _m(134000, 141000, _cls("TGAE"), "2 mm", "47 CFR 97.301(a)"),
    _m(241000, 250000, _cls("TGAE"), "1 mm", "47 CFR 97.301(a)"),
    # Missing until this check: 97.301(a)'s table has a row above every
    # other one, "Above 275" in all three Region columns with sharing (f),
    # and 97.305(c)(7)(vi) separately confirms it as emission-authorized
    # ("(vi) 1 mm / Above 275 GHz / MCW, phone, image, RTTY, data, SS,
    # test, pulse"). Part 97 states no upper edge, so the row is held open
    # at an arbitrary 1 THz sentinel, as rsm.py (NZ) already does for its
    # own "above 275 GHz" row.
    _m(275000, 1000000, _cls("TGAE"), "above 275 GHz; no upper edge stated",
       "47 CFR 97.301(a), 97.303(f); 97.305(c)(7)(vi)"),
]

# 60 m [us.md s.3.3; 97.303(h)(3), 97.307(f)(14), 97.313(i); in force from
# 13 Feb 2026]: General, Advanced and Extra, on four channels at 100 W ERP
# and in 5351.5-5366.5 kHz at 9.15 W ERP (15 W EIRP), never wider than
# 2.8 kHz. Each channel is a centre frequency; the signal must lie within
# centre +/- 1.4 kHz [derived: half of the 2.8 kHz the rule allows].
_SIXTY_SRC = "47 CFR 97.303(h)(3), 97.307(f)(14), 97.313(i); 47 CFR 2.106 US23"
_SIXTY_WHO = ("general", "advanced", "extra")


def _channel(centre_khz):
    lo, hi = (centre_khz - 1.4) * 1e3, (centre_khz + 1.4) * 1e3
    return {"lo": lo, "hi": hi, "label": f"60 m channel {centre_khz:g} kHz",
            "where": f"the 2.8 kHz centred on {centre_khz:g} kHz", "segments": [(lo, hi)],
            "limits": {c: ((100.0, "ERP"),) for c in _SIXTY_WHO}, "max_bw": 2800.0, "src": _SIXTY_SRC}


CHANNELLED = [
    _channel(5332.0), _channel(5348.0),
    {"lo": 5351.5e3, "hi": 5366.5e3, "label": "60 m (5351.5-5366.5 kHz)", "where": "5351.5-5366.5 kHz",
     "segments": [(5351.5e3, 5366.5e3)], "limits": {c: ((9.15, "ERP"),) for c in _SIXTY_WHO},
     "max_bw": 2800.0, "src": _SIXTY_SRC},
    _channel(5373.0), _channel(5405.0),
]

_SIXTY_GAP = ("In the United States, 60 m may be used only on the channels centred on 5332, 5348, 5373 and "
              "5405 kHz and in 5351.5-5366.5 kHz (47 CFR 97.303(h)(3)).")
REFUSED = [
    (5333.4e3, 5346.6e3, _SIXTY_GAP, "us.md s.3.3"),
    (5349.4e3, 5351.5e3, _SIXTY_GAP, "us.md s.3.3"),
    (5366.5e3, 5371.6e3, _SIXTY_GAP, "us.md s.3.3"),
    (5374.4e3, 5403.6e3, _SIXTY_GAP, "us.md s.3.3"),
    (219e6, 220e6, "219-220 MHz is only for fixed point-to-point digital message forwarding, after written "
                   "notice to ARRL and AMTS licensees (47 CFR 97.303(l)); OpenHamShack does not transmit there.",
     "us.md s.3.2, gaps"),
    (2310e6, 2390e6, "2310-2390 MHz is not an amateur band in the United States (47 CFR 97.301(a)).",
     "us.md s.3.2, gaps"),
    (3300e6, 3450e6, "3300-3450 MHz is not in Part 97: amateurs continue there only under footnote US103, which "
                     "names no class or power and may be withdrawn at any time, so OpenHamShack does not transmit "
                     "there.", "us.md s.3.2 and s.11 item 1; 47 CFR 2.106 US103"),
    (3450e6, 3500e6, "3450-3500 MHz stopped being an amateur band on 14 April 2022.", "us.md s.3.2, gaps; F5"),
]

# Per-segment emissions (97.305(c), 97.307(f)), us.md s.4. CW is allowed
# wherever the operator may transmit (97.305(a)), so it is in every set.
# RTTY/data segments on HF are 2.8 kHz at most (97.307(f)(3)); phone and
# image segments are phone and image. Region 3, and Region 2 west of 130 W
# or south of 20 N, may also use phone on 7075-7100 kHz (97.307(f)(11));
# EMISSIONS cannot say where the station is, so 7000-7125 kHz is held to
# CW and data everywhere - the stricter reading.
_ALL = ("novice", "technician", "general", "advanced", "extra")
_DATA = frozenset({"cw", "digi"})
_PHONE = frozenset({"cw", "ssb", "am", "fm", "dv", "image"})
_CW = frozenset({"cw"})


def _em(lo_khz, hi_khz, modes, max_bw, note, src, who=_ALL):
    return (lo_khz * 1e3, hi_khz * 1e3, {c: modes for c in who}, max_bw, note, src)


_NT = ("novice", "technician")
EMISSIONS = [
    _em(3500, 3600, _DATA, 2800.0, "80 m RTTY/data", "47 CFR 97.305(c), 97.307(f)(3)"),
    _em(3600, 4000, _PHONE, None, "75 m phone/image", "47 CFR 97.305(c)"),
    _em(7000, 7125, _DATA, 2800.0, "40 m RTTY/data (phone on 7075-7100 kHz only in some places: not encoded)",
        "47 CFR 97.305(c), 97.307(f)(3),(11)"),
    _em(7125, 7300, _PHONE, None, "40 m phone/image", "47 CFR 97.305(c)"),
    _em(10100, 10150, _DATA, 2800.0, "30 m: no phone", "47 CFR 97.305(c), 97.307(f)(3)"),
    _em(14000, 14150, _DATA, 2800.0, "20 m RTTY/data", "47 CFR 97.305(c), 97.307(f)(3)"),
    _em(14150, 14350, _PHONE, None, "20 m phone/image", "47 CFR 97.305(c)"),
    _em(18068, 18110, _DATA, 2800.0, "17 m RTTY/data", "47 CFR 97.305(c), 97.307(f)(3)"),
    _em(18110, 18168, _PHONE, None, "17 m phone/image", "47 CFR 97.305(c)"),
    _em(21000, 21200, _DATA, 2800.0, "15 m RTTY/data", "47 CFR 97.305(c), 97.307(f)(3)"),
    _em(21200, 21450, _PHONE, None, "15 m phone/image", "47 CFR 97.305(c)"),
    _em(24890, 24930, _DATA, 2800.0, "12 m RTTY/data", "47 CFR 97.305(c), 97.307(f)(3)"),
    _em(24930, 24990, _PHONE, None, "12 m phone/image", "47 CFR 97.305(c)"),
    _em(28000, 28300, _DATA, 2800.0, "10 m RTTY/data", "47 CFR 97.305(c), 97.307(f)(3)"),
    _em(28300, 29700, _PHONE, None, "10 m phone/image", "47 CFR 97.305(c)"),
    # Novice and Technician: international Morse only on their 80/40/15 m
    # segments, CW or SSB (J3E/R3E) on 28.3-28.5 MHz.
    _em(3525, 3600, _CW, None, "Novice/Technician CW only", "47 CFR 97.307(f)(9)", _NT),
    _em(7025, 7125, _CW, None, "Novice/Technician CW only", "47 CFR 97.307(f)(9)", _NT),
    _em(21025, 21200, _CW, None, "Novice/Technician CW only", "47 CFR 97.307(f)(9)", _NT),
    _em(28300, 28500, frozenset({"cw", "ssb"}), None, "Novice/Technician CW or SSB only", "47 CFR 97.307(f)(10)",
        _NT),
    _em(50000, 50100, _CW, None, "6 m CW only", "47 CFR 97.305(c)(4)"),
    _em(144000, 144100, _CW, None, "2 m CW only", "47 CFR 97.305(c)(4)"),
]

# Where the station is, and what it has notified (us.md s.3.4). Each
# defaults to the answer that refuses or limits.
_NOTIFY = ("{band} may be used only from a fixed station whose location was notified to the Utilities Telecom "
           "Council at least 30 days ago without objection (47 CFR 97.303(g)); tick it in Settings › Licence & "
           "plan if this station's was.")
_CO_WY = "47 CFR 97.303(n)(3)"
CONDITIONS = [
    {"key": "utcNotified2200m", "lo": 135.7e3, "hi": 137.8e3, "default": False, "when": False,
     "label": "2200 m: this fixed station was notified to UTC at least 30 days ago, without objection",
     "refuse": _NOTIFY.format(band="2200 m (135.7-137.8 kHz)"), "src": "47 CFR 97.303(g)"},
    {"key": "utcNotified630m", "lo": 472e3, "hi": 479e3, "default": False, "when": False,
     "label": "630 m: this fixed station was notified to UTC at least 30 days ago, without objection",
     "refuse": _NOTIFY.format(band="630 m (472-479 kHz)"), "src": "47 CFR 97.303(g)"},
    {"key": "alaskaNearRussia", "lo": 472e3, "hi": 479e3, "default": True,
     "label": "Station in Alaska within 800 km of Russia", "limit": Limit(1.0, "EIRP"),
     "src": "47 CFR 97.313(l)"},
    {"key": "northOfLineA", "lo": 420e6, "hi": 430e6, "default": True,
     "label": "Station north of Line A",
     "refuse": ("No amateur station may transmit on 420-430 MHz from north of Line A (47 CFR 97.303(m)(1)); "
                "untick it in Settings › Licence & plan if this station is south of it."),
     "src": "47 CFR 97.303(m)(1), 97.3(a)(30)"},
    {"key": "inUs270Area", "lo": 420e6, "hi": 450e6, "default": True,
     "label": "Station in a 70 cm radar area of footnote US270", "limit": Limit(50.0, _P),
     "src": "47 CFR 97.313(f); 47 CFR 2.106 US270"},
    {"key": "inWhiteSandsBox", "lo": 902e6, "hi": 928e6, "default": True,
     "label": "Station inside the White Sands box (31°41'-34°30'N, 104°11'-107°30'W)",
     "refuse": ("33 cm may not be used inside the White Sands Missile Range box, 31°41'-34°30'N and "
                "104°11'-107°30'W (47 CFR 97.303(n)); untick it in Settings › Licence & plan if this station "
                "is outside it."), "src": "47 CFR 97.303(n)(2)"},
    {"key": "nearWhiteSands", "lo": 902e6, "hi": 928e6, "default": True,
     "label": "Station within 241 km of White Sands Missile Range", "limit": Limit(50.0, _P),
     "src": "47 CFR 97.313(g)"},
] + [
    {"key": "inColoradoWyomingBox", "lo": a * 1e6, "hi": b * 1e6, "default": True,
     "label": "Station inside the Colorado/Wyoming box (39-42°N, 103-108°W)",
     "refuse": (f"{a:g}-{b:g} MHz may not be used inside the Colorado/Wyoming box, 39-42°N and 103-108°W "
                f"({_CO_WY}); untick it in Settings › Licence & plan if this station is outside it."),
     "src": _CO_WY}
    for a, b in ((902.4, 902.6), (904.3, 904.7), (925.3, 925.7), (927.3, 927.7))
]

# The amateur-satellite service (us.md s.6). RR 5.282, part of 47 CFR
# 2.106 [F4]: 435-438 and 2400-2450 MHz, 1260-1270 and 5650-5670 MHz
# Earth-to-space only. 97.207(c) lists where space stations may transmit;
# us.md gives no Earth-to-space status for those, so they are "down".
_SAT_207 = "47 CFR 97.207(c)"
_SAT_282 = "47 CFR 2.106, RR 5.282"
SATELLITE = [
    (7000e3, 7100e3, "down", _SAT_207), (14000e3, 14250e3, "down", _SAT_207),
    (18068e3, 18168e3, "down", _SAT_207), (21000e3, 21450e3, "down", _SAT_207),
    (24890e3, 24990e3, "down", _SAT_207), (28000e3, 29700e3, "down", _SAT_207),
    (144e6, 146e6, "down", _SAT_207), (435e6, 438e6, "both", _SAT_282),
    (1260e6, 1270e6, "up", _SAT_282), (2400e6, 2450e6, "both", _SAT_282 + "; " + _SAT_207),
    (5650e6, 5670e6, "up", _SAT_282), (5830e6, 5850e6, "down", _SAT_207),
    (10450e6, 10500e6, "down", _SAT_207), (24000e6, 24050e6, "down", _SAT_207),
    (47000e6, 47200e6, "down", _SAT_207), (76000e6, 81000e6, "down", _SAT_207),
    (134000e6, 141000e6, "down", _SAT_207), (241000e6, 250000e6, "down", _SAT_207),
]

# Reciprocal operation (us.md s.8). Abroad, for US citizens: Extra and
# Advanced are the CEPT Radio Amateur Licence; General is the CEPT Novice,
# only where ECC/REC (05)06 is implemented [F6, C1, C2]. In the US, a CEPT
# licence holder has 97.301(a) and (b): Amateur Extra [C1 Annex 4].
CEPT = {"T/R 61-01": ("advanced", "extra"), "ECC/REC (05)06": ("general",)}
CEPT_SRC = ("FCC Public Notice DA 16-1048 (16 Sep 2016); CEPT T/R 61-01 (18 Oct 2024) Annex 4; "
            "ECC/REC (05)06 (16 Jun 2023) Annex 4; 47 CFR 97.301(a),(b)")
CEPT_VISITOR = {"T/R 61-01": "extra"}

NOTES = [
    ("repeater", "Repeaters may not operate on 28.0-29.5, 50.0-51.0, 144.0-144.5, 145.5-146.0, 222.00-222.15, "
                 "431.0-433.0 or 435.0-438.0 MHz.", "47 CFR 97.205"),
    ("beacon", "Beacons: at most 100 W, one channel per band; automatic control only in the segments 97.203 "
               "lists.", "47 CFR 97.203"),
    ("satellite", "Earth and telecommand stations may use up to 611 W ERP (1 kW EIRP) on 435-438 MHz with the "
                  "antenna elevated above 10 degrees.", "47 CFR 97.313(f)"),
    ("spread spectrum", "Spread spectrum is limited to 10 W PEP.", "47 CFR 97.313(j)"),
    ("visitors", "A Canadian visitor operates on Canadian terms, never beyond Amateur Extra, and signs with the "
                 "US indicator after the call (VE3ABC/W4).", "47 CFR 97.107(a), 97.119(g)"),
    ("altitude", "These privileges apply to a station within 50 km of the Earth's surface.",
     "47 CFR 97.301 preamble"),
]
