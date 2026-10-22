"""QO-100 narrowband transponder: frequencies, bandplan and the transmit guard.

Every number here comes from docs/qo100-research.md (AMSAT-DL's bandplan
page, the beacon page and the IARU R1 emergency notice). All frequencies are
Hz and use the vocabulary in DESIGN.md: `dl` is the downlink the operator
sees, `ul` the uplink we actually transmit on.
"""
from __future__ import annotations

# Non-inverting conversion: downlink = uplink + 8089.5 MHz. The satellite's
# own LO error is not modelled here - it shifts the beacons and us alike, so
# beacon lock (rxCorr) already contains it.
TRANSPONDER_LO = 8_089_500_000.0
DL_LO, DL_HI = 10_489_500_000.0, 10_490_000_000.0
UL_LO, UL_HI = DL_LO - TRANSPONDER_LO, DL_HI - TRANSPONDER_LO

# The licence/bandplan limit on any signal's occupied bandwidth.
MAX_BW = 2700.0


def ul(dl: float) -> float:
    return dl - TRANSPONDER_LO


def dl(ul_hz: float) -> float:
    return ul_hz + TRANSPONDER_LO


def mhz(hz: float, places: int = 4) -> str:
    return f"{hz / 1e6:.{places}f}"


# Beacons. `track` is what BeaconTracker locks to: the F1A beacons are
# located by their two tones 400 Hz apart, the mid-band beacon by squaring its
# carrier-less BPSK. `ref` is the frequency the measured centre must land on
# once rxCorr is right - for F1A that is the midpoint of the pair (DJ0ABR's
# method), for BPSK the suppressed carrier itself.
BEACONS = {
    "lower": {"name": "Lower beacon (CW F1A)", "dl": 10_489_500_000.0, "kind": "f1a", "shift": 400.0,
              "ref": 10_489_500_200.0},
    "middle": {"name": "Middle beacon (400 bd BPSK)", "dl": 10_489_750_000.0, "kind": "bpsk", "baud": 400.0,
               "ref": 10_489_750_000.0},
    "mm": {"name": "Multimedia beacon (8APSK)", "dl": 10_489_995_000.0, "kind": "mm", "ref": 10_489_995_000.0},
    # The upper beacon's two tones are 10489.9996 and 10490.0000 - both
    # inside its segment, which ends at 10490.000 - so its midpoint is 200 Hz
    # below the nominal frequency, the mirror of the lower beacon's. Seen in
    # Brian's recording of 07/10/2026 (after-dish): 400 Hz apart, keyed in
    # step with the lower beacon with the same text, but its mark is the
    # *lower* tone (space at 10490.000), as destevez.net's "Measuring QO-100
    # beacons frequency" (2019, comments) has it. Only click-to-lock uses
    # it: the tracker follows lower and middle.
    "upper": {"name": "Upper beacon (CW)", "dl": 10_490_000_000.0, "kind": "f1a", "shift": 400.0,
              "ref": 10_489_999_800.0},
}

# Mode classes the bandplan talks about. A QO-100 NB mode maps to exactly one.
MODE_CLASS = {
    "usb": "ssb", "lsb": "ssb", "am": "ssb", "cw": "cw",
    "ft8": "digital", "ft4": "digital", "q65": "digital", "js8": "digital", "psk31": "digital", "psk63": "digital",
    "psk125": "digital", "rtty": "digital", "freedv": "digital", "sstv": "digital", "hsmodem": "digital",
    "kgstv": "digital",
}

# (dl_lo, dl_hi, label, allowed mode classes or None for "no transmitting", max occupied bandwidth)
# FreeDV is filed under digital: AMSAT-DL's "SSB only" segments mean analogue
# SSB, and its activity days sit at 10489.640, inside the 2.7 kHz digimode
# segment. The broadcast slot is AMSAT-DL's own bulletin channel, so it is
# refused rather than guessed at.
SEGMENTS = [
    (10_489_500_000.0, 10_489_505_000.0, "lower beacon", None, 0.0),
    (10_489_505_000.0, 10_489_540_000.0, "CW only", {"cw"}, MAX_BW),
    (10_489_540_000.0, 10_489_580_000.0, "narrow digimodes (500 Hz max)", {"digital", "cw"}, 500.0),
    (10_489_580_000.0, 10_489_650_000.0, "digimodes (2.7 kHz max)", {"digital", "cw"}, MAX_BW),
    (10_489_650_000.0, 10_489_745_000.0, "SSB only", {"ssb"}, MAX_BW),
    (10_489_745_000.0, 10_489_755_000.0, "middle beacon", None, 0.0),
    (10_489_755_000.0, 10_489_850_000.0, "SSB only", {"ssb"}, MAX_BW),
    (10_489_850_000.0, 10_489_857_500.0, "AMSAT-DL broadcast", None, 0.0),
    (10_489_857_500.0, 10_489_865_000.0, "emergency (10489.860)", {"ssb", "cw", "digital"}, MAX_BW),
    (10_489_865_000.0, 10_489_990_000.0, "mixed modes, contests", {"ssb", "cw", "digital"}, MAX_BW),
    (10_489_990_000.0, 10_489_997_000.0, "multimedia beacon", None, 0.0),
    (10_489_997_000.0, 10_490_000_000.0, "upper beacon", None, 0.0),
]

# Built-in memories: useful places to tune, from the research. Operator
# memories are stored alongside these in the config, never replacing them.
# The beacons' bookmarks put the MARK tone on the default CW pitch (700 Hz),
# so the CW decoder hears the keying and the space tone, 400 Hz away, falls
# outside the 500 Hz CW filter. They used to put 10489.500 / 10490.000 on
# the pitch, which is each beacon's SPACE tone: the decoder then heard the
# keying upside down (a tone in every gap, silence in every element) and
# printed strings of unknown letters - Brian's TV, 10/10/2026. Lower beacon:
# mark 10489.5004 (the upper tone); upper beacon: mark 10489.9996 (the lower
# tone) - both from the recording of 07/10/2026 (BEACONS above).
CW_PITCH = 700.0   # cwPitch's default (ohscore/state.py)
PRESETS = [
    {"name": "Lower beacon", "dl": 10_489_500_400.0 - CW_PITCH, "mode": "cw"},
    {"name": "Middle beacon (PSK)", "dl": 10_489_750_000.0 - 1500.0, "mode": "usb"},
    {"name": "Upper beacon", "dl": 10_489_999_600.0 - CW_PITCH, "mode": "cw"},
    {"name": "CW segment", "dl": 10_489_520_000.0, "mode": "cw"},
    {"name": "FT8", "dl": 10_489_540_000.0, "mode": "ft8"},
    {"name": "Q65-60A", "dl": 10_489_545_000.0, "mode": "q65"},
    {"name": "JS8Call", "dl": 10_489_548_000.0, "mode": "js8"},
    {"name": "FreeDV activity", "dl": 10_489_640_000.0, "mode": "freedv"},
    {"name": "SSB lower", "dl": 10_489_700_000.0, "mode": "usb"},
    {"name": "SSB upper", "dl": 10_489_800_000.0, "mode": "usb"},
    {"name": "Emergency", "dl": 10_489_860_000.0, "mode": "usb"},
    {"name": "Contest FT4/FT8", "dl": 10_489_870_000.0, "mode": "ft8"},
]


def segment_at(f: float) -> dict | None:
    for lo, hi, label, classes, maxbw in SEGMENTS:
        if lo <= f < hi or (f == DL_HI and hi == DL_HI):
            return {"lo": lo, "hi": hi, "label": label, "tx": classes is not None,
                    "modes": sorted(classes) if classes else [], "maxBw": maxbw}
    return None


def _segment(label: str) -> tuple[float, float]:
    """A segment's edges by its label, so MODE_SPOTS reads off SEGMENTS
    itself rather than repeating its frequencies."""
    for lo, hi, lab, _classes, _maxbw in SEGMENTS:
        if lab == label:
            return lo, hi
    raise KeyError(label)


def _preset(name: str) -> float:
    """A built-in preset's downlink by its name, for the same reason."""
    return next(p["dl"] for p in PRESETS if p["name"] == name)


_NARROW_LO, _NARROW_HI = _segment("narrow digimodes (500 Hz max)")
_WIDE_LO, _WIDE_HI = _segment("digimodes (2.7 kHz max)")
_CW_LO, _CW_HI = _segment("CW only")
_CONTEST_DL = _preset("Contest FT4/FT8")
_MODE_TOL = 3_000.0     # "already there" margin outside a segment's own edge (Brian, 07/10/2026)

# Where each mode is usually operated on QO-100, for Engine.set_mode_tuned
# (Settings' "tune to the usual frequency on mode", on by default): each
# entry is (target, window_lo, window_hi) - inside the window the dial
# already counts as "there", so picking the mode leaves it; otherwise the
# nearest target is used. FT8 and FT4 share the narrow-digi calling
# frequency and the AMSAT-DL contest zone's FT4/8 mark (both narrowband,
# interchangeable in practice); Q65 (Q65-60A) and FreeDV (its activity-day
# slot) each have one place, inside the segment holding them; CW's is the
# built-in "CW segment" preset, anywhere in the CW-only segment counting
# as "there" already. PSK31, PSK63, PSK125, RTTY, SSTV and HSmodem have no
# documented QO-100 calling frequency (docs/qo100-research.md: "no
# conventional calling frequency found", "unverified convention", or
# nothing at all) - omitted here, so picking them never retunes. (The
# multimedia beacon is HSmodem, but it is received in the background
# whatever the dial - Beacon - and NB's HSmodem mode is station to
# station, which the beacon's segment refuses.)
#
# FT8, Q65 and JS8 all live in the narrow digimode segment, 5 and 8 kHz
# apart. Until 17/10/2026 each counted the whole segment as "there", so
# from FT8's .540 a Q65 or JS8 press left the dial on the FT8 signals
# (Mac test, findings 17 and 22). Now the segment is shared out: FT8 up to
# Q65's mark, Q65 up to JS8's, JS8 the rest - each window starting at its
# own mark, as a dial a little above a mark is still on that mode's
# signals and one below it is on the mode below.
_Q65_DL = _preset("Q65-60A")
_JS8_DL = _preset("JS8Call")
MODE_SPOTS: dict[str, list[tuple[float, float, float]]] = {
    "ft8": [(_preset("FT8"), _NARROW_LO - _MODE_TOL, _Q65_DL - 1.0),
            (_CONTEST_DL, _CONTEST_DL - _MODE_TOL, _CONTEST_DL + _MODE_TOL)],
    "ft4": [(_preset("FT8"), _NARROW_LO - _MODE_TOL, _Q65_DL - 1.0),
            (_CONTEST_DL, _CONTEST_DL - _MODE_TOL, _CONTEST_DL + _MODE_TOL)],
    "q65": [(_Q65_DL, _Q65_DL, _JS8_DL - 1.0)],
    # JS8Call (receive only, ohscore/modes/js8.py): the existing preset's own
    # frequency, cited to OH8STN 2026 (docs/qo100-research.md).
    "js8": [(_JS8_DL, _JS8_DL, _NARROW_HI)],
    "freedv": [(_preset("FreeDV activity"), _WIDE_LO, _WIDE_HI)],
    "cw": [(_preset("CW segment"), _CW_LO, _CW_HI)],
}


# What one signal of each message mode occupies, Hz: the band holding
# 99.5 % of the power of audio its encoder renders - the measure send()
# applies to every message it is about to transmit (engine._occupied).
# Measured 06/10 with a CQ for FT8/FT4/PSK/RTTY and a test card for SSTV,
# rounded up. Used when there is no message to measure: idle (the TX
# button's state and tooltip) and plain PTT, which in these modes carries
# another program's signal of the same mode through a loopback device -
# and a 2.4 kHz SSB filter is not what FT4 sends. JS8 (sent since
# 17/10/2026) measured the same way from its encoder at each speed, on a CQ,
# a heartbeat and a three-frame message: Slow 26-30 Hz, Normal 56-61, Fast
# 84-95, Turbo 168-191, Ultra 262-298. One width per mode, so the widest,
# Ultra's, rounded up: an over is judged by its own measured audio anyway,
# and this only judges a key-up before one is rendered.
# KG-STV measured the same way from its encoder (ohscore/modes/kgstv.py,
# which band-limits MSK to its main lobe; it says why) at every quality, on
# pictures received on ohs-box, a screenshot, black and noise: 1393-1408 Hz,
# with 20 Hz to spare, rounded up to 10. It fits the 2.7 kHz digimode
# segment where KG-STV is used, never the 500 Hz narrow one.
SIGNAL_WIDTH = {"ft8": 55.0, "ft4": 90.0, "q65": 115.0, "psk31": 55.0, "psk63": 105.0, "psk125": 205.0,
                "rtty": 320.0, "sstv": 1250.0, "kgstv": 1430.0, "js8": 300.0}
# FreeDV's modem by waveform, measured the same way from its streamer fed
# speech-like noise. PTT keys FreeDV, so this is also what a key-up is
# judged by. 700E was not installed to measure: it keeps the passband's
# (over-)estimate rather than a guessed number.
FREEDV_WIDTH = {"700c": 1500.0, "700d": 1300.0, "1600": 1250.0, "2020": 1700.0}
# HSmodem by speed (bit/s), measured the same way (07/10) from what the
# encoder renders - the most of five contents (pictures, text, random and
# empty files: the content moves it by up to 25 Hz) - with 20 Hz to spare,
# rounded up to 10: RRC 0.2 at the symbol
# rate, so 1.1 times the baud by this measure (1.2 times edge to edge -
# 2.88 kHz at 2400 Bd - with the last 0.5 % of the power in the roll-off).
# DJ0ABR's GUI labels the 2400 Bd speeds "BW: 2700 Hz". Every one fits
# MAX_BW; HSMODEM_SPEEDS is what NB offers, so one that did not would
# never be offered, and send() measures each transmission again besides.
HSMODEM_WIDTH = {1200: 1340.0, 2400: 2660.0, 3000: 1680.0, 4000: 2230.0, 4410: 2460.0, 4800: 2680.0,
                 5500: 2070.0, 6000: 2250.0, 6600: 2480.0, 7200: 2690.0}
HSMODEM_SPEEDS = tuple(b for b, w in sorted(HSMODEM_WIDTH.items()) if w <= MAX_BW)


def tx_blocked(lo: float, hi: float, mode: str, widths: bool = True, width: float | None = None) -> str:
    """Why a transmission occupying downlink [lo, hi] Hz in `mode` must not
    happen, or '' if it may. Both edges of the occupied signal are judged,
    not the dial: an SSB signal dialled 100 Hz under a segment edge still
    puts 2.6 kHz of speech inside the next segment.

    widths=False skips the bandwidth limits and judges only where [lo, hi]
    reaches: for a signal known only by the passband it could be anywhere
    in (an external radio's digital mode, whose tones the sending program
    places), the passband's width says nothing about the signal's.
    `width`, when the signal's own width is known but not yet where in
    [lo, hi] it will sit (a digital mode before its panel sends), judges
    the limits by that width instead.

    Judged by the shared dataset's QO-100 NB plan (ohs-libs data/bandplan/
    satellite/qo100-nb.json, through ohscore/txguard.py) with the licence set
    aside: the station's licence is _uplink_refusal's question, and this
    one is answered whether or not a licence is set (NB warns, not locks,
    without one). SEGMENTS above stays for drawing the plan on the scope;
    tests/test_bandplan.py proves the two agree. Only "is this a mode NB
    transmits" is NB's own question, not the plan's."""
    if hi < lo:
        lo, hi = hi, lo
    if MODE_CLASS.get(mode) is None:
        return f"{mode} is not a mode OpenHamShack QO-100 NB transmits"
    from ohscore import txguard
    v = txguard.GUARD.check(txguard.PLAN_ONLY, ul(lo), ul(hi), mode=mode, satellite="qo100-nb",
                            signal_bw=(width if widths else 0.0))
    return v.refused
