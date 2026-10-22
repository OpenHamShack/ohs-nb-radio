"""OpenHamShack Radio's engine: ohscore.engine.Engine on the amateur bands.

The engine itself - threads, set/state, feeds, the safety supervisor
(transmit time-out, dead air, the UI watchdog), the transmit loop,
ptt/send, memories and the log - is ohscore/engine.py, shared with OpenHamShack
NB; its docstring describes the threads and the safety rules. What makes
it a terrestrial multi-band transceiver is here, in the hooks Engine
calls (docs/ham/DESIGN-HAM.md sections 3-6):

- **frequencies**: the dial is the on-air frequency (`rf`). The receiver's
  centre follows the band: a band narrower than the device's span sits
  wholly on one side of DC (so DC and its spur are off the band and the
  whole band is on the scope); a wider one keeps the dial in view, DC a
  quarter of the span below it, re-centring only when the dial leaves the
  span. The device's reference error (`ppm`) is taken out of every tune.
- **dials**: the transmit dial adds a repeater shift in FM (auto from the
  plan's UK channel pairs, or minus/plus by hand) and reverse swaps input
  and output;
- **the guard** (ohsradio/guard.py): the licence (always), the device's
  reach, the band plan (warn by default, beacon and satellite segments
  always refused), a band that has no radio yet;
- **power**: `drive` through the band's power chain (ohsradio/power.py) to an
  estimated PEP. Advisory until measured (Brian, 05/10/2026): an estimate
  over the licence's limit warns (licenceInfo, and the transmit card's
  standing warning) but does not refuse; where the radio measures forward power
  and nothing entered sits between it and the feeder (no PA gain), the
  measurement is held to the limit and an excess unkeys, like the SWR
  trip. The slider can never pass the band's ceiling;
- **transmit choreography**: the PTT sequencer's line first, the TX LO a
  quarter of the sample rate below the signal (so its leakage is not on
  the transmit channel), drive ramped up from zero, and the reverse on
  key-down; while keyed, measured SWR and PA temperature unkey
  (rule 7);
- **FM**: demodulated from its own 24 kS/s channel with noise squelch,
  tone squelch and the CTCSS tone heard; modulated with CTCSS and the
  1750 Hz toneburst (ohscore/dsp/fm.py); AM transmits;
- **half duplex**: receive audio is muted while keyed;
- **band stacks**: three registers per band, recalled and cycled by
  band(); the log's ADIF says which band from the frequency;
- **converters** (ohsradio/xvtr.py): a band worked through a transverter or
  up/down-converter keeps its dial, guard, band bar and log on the air;
  only the device is told the converter's IF, an inverting one has the
  IQ mirrored at the device, and the drive into one is held under its
  most drive.

    radio = Radio(cfg)           # does not open the device or transmit
    radio.start() / stop() / set(...) / ptt(on) / send(mode, **msg) / band(name) / toneburst() / tune(on)
"""
from __future__ import annotations

import math
import time

import numpy as np

from ohscore import converters as cv
from ohscore import licences, txguard
from ohscore.dsp.bank import Channel, Source
from ohscore.dsp.fm import FM_RATE, FmDemod, FmMod
from ohscore.dsp.mod import AmMod
from ohscore.engine import AUDIO_RATE, Engine, TxRefused

from ohsradio.i18n import _

from . import bands, config, guard, power, state, xvtr
from .cwskim import CwSkim, off_item
from .devices import REGISTRY
from . import plans
from .plans import repeaters
from .sequencer import Sequencer, SequencerError, make_output

# cwskim and cwspot: the CW skimmer (cwskim.py, docs/ENGINE-API.md). Never in
# the server's default set, so a client gets them only when it asks.
FEED_KINDS = ("wide", "zoom", "events", "meter", "state", "toast", "cwskim", "cwspot")
# How long after a re-centring the receive channel is taken to hold the
# new centre's samples (Radio._rx_settled): a device read and the analysis
# bank's overlap are a few tens of milliseconds at every supported rate;
# a tenth of a second is short against what auto-tune listens to (4 s).
RETUNE_SETTLE = 0.1
USABLE = 0.46          # of fs/2: how far from DC the scope and the channels may go
DC_GUARD = 15_000.0    # a band that fits keeps DC this far below its lower edge
TX_OFFSET = 0.25       # of fs: the signal sits this far above the TX LO
TX_REACH = 0.40        # of fs: furthest the NCO may put the signal from the LO
DEVICE_FULL_W = {"pluto": 0.0045, "hl2": 5.0, "soapy": 0.0}
SWR_MIN_FWD = 0.05     # W: below this the reflected reading is noise (Quisk's figure)
MEASURING = ("hl2", "sim")   # devices whose telemetry reports forward power
OVER_READINGS = 2      # consecutive readings over the licence before unkeying
MODE_TUNE_TOL = 3_000.0   # Engine.set_mode_tuned: "already there" margin either side of a band's usual dial
_BAND = object()       # _device_full_w / _drive_limit: the converter the band's settings give
ADIF_BAND = {"160m": "160m", "80m": "80m", "60m": "60m", "40m": "40m", "30m": "30m", "20m": "20m", "17m": "17m",
             "15m": "15m", "12m": "12m", "10m": "10m", "6m": "6m", "4m": "4m", "2m": "2m", "70cm": "70cm",
             "23cm": "23cm", "13cm": "13cm", "9cm": "9cm", "6cm": "6cm"}


def presets(plan=plans.rsgb_2026) -> list[dict]:
    """Built-in memories: the band plan's centres of activity and each band's FT8 dial.
    The plan is the one in force (Radio._plan): an operator in Canada gets
    IARU Region 2's centres, not the RSGB's "UK emergency".
    Not on a deferred band (6 m): a memory there could only be recalled to
    be refused. The band's data stays in bands.py for when a radio covers it."""
    def usable(f: float) -> bool:
        b = bands.band_at(f)
        return b is None or not b.deferred
    out = [{"name": f"{lab} {f / 1e6:.4f}".rstrip("0").rstrip("."), "rf": float(f), "mode": m}
           for f, lab, m in plan.CENTRES if usable(f)]
    out += [{"name": f"FT8 {b.name}", "rf": float(b.ft8), "mode": "ft8"} for b in bands.BANDS
            if b.ft8 and not b.deferred]
    return out


def plan_centre(dial: float, band: bands.Band | None, fs: float, rx_range: tuple[float, float]) -> float:
    """Where the receiver's centre (DC) should be for `dial` (module docstring)."""
    half = USABLE * fs / 2
    width = band.hi - band.lo if band is not None and band.lo <= dial <= band.hi else None
    if width is not None and width + DC_GUARD <= half - 5_000:
        c = band.lo - DC_GUARD                   # all of it on one side of DC
    elif width is not None and width + 10_000 <= 2 * half:
        c = (band.lo + band.hi) / 2              # all of it on the scope, DC in the middle
    else:
        c = dial - fs / 8                        # follow the dial, DC a little below it
    c = max(c, rx_range[0])
    c = min(c, rx_range[1])
    return round(c / 1000.0) * 1000.0


class Radio(Engine):
    STATE = state.REG
    CONFIG = config.CONFIG
    DEVICES = REGISTRY
    FEED_KINDS = FEED_KINDS
    PRESETS = presets()
    FREQ_KEY = "rf"
    LOG_TITLE = "OpenHamShack Radio log export"
    PROGRAM_ID = "OpenHamShack Radio"
    APP_ID = "shack-radio"
    THREAD_PREFIX = "ohsradio"
    LOGGER = "ohsradio.radio"
    DERIVE_ON = ("keyed",)
    # The repeater shift, its size and reverse all move the transmit dial.
    # Drive, the Tune share and the power chain move what reaches a
    # transverter's input: an over keyed under its most drive must not be
    # turned up past it (the converter safety review, 07/10/2026).
    # And the converter list and which band uses which: Settings can point
    # the over's band at another converter (a receive-only one) while it
    # waits for its slot.
    RECHECK_KEYED = Engine.RECHECK_KEYED + ("rptShift", "rptOffsetHz", "rptReverse", "drive", "tuneDrive",
                                            "bandPower", "converters", "bandConverters")
    # Every setting that moves the transmit dial, and so may put it behind
    # another converter with another drive limit.
    TX_DIAL_KEYS = ("vfo", "txVfo", "split", "xit", "xitOn", "rptShift", "rptOffsetHz", "rptReverse", "mode")
    # Band changes reopen nothing but retune everything, and the sequencer
    # and SWR trip are where a keying problem would show.
    DIAG_WATCH = Engine.DIAG_WATCH + ("band", "seqState", "swrTripped")
    APP_NAME = "OpenHamShack Radio"
    APP_PACKAGE = "ohsradio"
    # No F1A beacons on Radio's bands, and on 17 m an NCDXF beacon's
    # fading 1 s dashes turned the CW decoder inside out for the next
    # station ("CS3B" read "I*ETV T"; ohs-libs shack_cw.corpus).
    CW_POLARITY = False
    REC_STATES = ("band",)

    def _diag_extra(self, s: dict) -> str:
        info = s.get("licenceInfo") or {}
        return (f"{s.get('band') or '--'} seg {s.get('segment') or '-'} | {info.get('class') or 'no-class'} "
                f"tx:{info.get('level', '')} seq {s.get('seqState')}"
                + (f" swr {s['swr']:.2f} fwd {s['fwdW']:.1f} W" if s.get("keyed") else ""))

    # The CW skimmer's worker: a child process on the box and the desktop
    # (Brian, 13/10/2026), a thread in tests.
    CWSKIM_MODE = "process"

    def __init__(self, *a, **kw):
        self.cwskim: CwSkim | None = None
        super().__init__(*a, **kw)
        self.centre = None
        self.pending_centre = None
        self.settle_at = 0          # rx_samples from which a re-centring has reached the channels
        self.tx_lo = None
        self.seq = None
        self.swr_avg = None
        self.ctcss_heard = 0.0
        self.over_count = 0
        self.st["seqState"] = "rx"
        # The converter the receiver works through now (with the centre),
        # the one waiting to be applied with pending_centre, and the one the
        # current over goes out through.
        self.rx_conv: cv.Converter | None = None
        self.pending_conv: cv.Converter | None = None
        self.tx_conv: cv.Converter | None = None
        self._presets_for = None
        self._refresh_presets()

    # ------------------------------------------------------------------ licence and plan
    def _plan(self):
        """The band plan in force: the operator's choice, else the station
        country's (ohsradio/plans choose())."""
        inf = self.licence_in_force()
        st = inf.station
        return plans.get(plans.choose(self.st.get("plan", plans.AUTO), st.country.plan if st.country else "",
                                      getattr(inf.regime, "PLAN", ""), st.region))

    def _repeaters(self) -> tuple[list, dict]:
        """(schemes, per-band offsets) for repeater shifts here: the plan in
        force's, or the station country's pairs (ohsradio/plans/repeaters.py).
        The UK's used to apply everywhere, which put a German 70 cm user
        on the wrong side of every repeater."""
        inf = self.licence_in_force()
        iso = inf.station.country.iso if inf.station.country else ""
        chosen = self.st.get("plan", plans.AUTO) not in ("", plans.AUTO)
        return repeaters.for_station(self._plan(), iso, chosen)

    def _refresh_presets(self) -> None:
        p = self._plan()
        if p is not self._presets_for:
            self._presets_for = p
            self.mem.presets = presets(p)

    def _judge(self, lo: float, hi: float, pep: float | None, gain: float, measured: bool = False,
               mode: str | None = None, width: float | None = None,
               plan_guard: str | None = None) -> tuple["guard.Verdict", "guard.Verdict"]:
        """(licence, band plan) for a signal on [lo, hi] at `pep` W PEP at
        the antenna, from one check of the shared dataset against the
        station profile (ohscore/txguard.py): the licence in force (the
        station country's, the operator's chosen one or their own), the
        plan in force (the operator's choice, else the country's) under
        `plan_guard` (default the planGuard setting), and the plan's
        reserved segments, refused whatever the guard says. `width` is one
        signal's own width for the plan's bandwidth limits (a digital mode
        anywhere in its dial window).

        Two verdicts because the transmit card shows the licence's power
        warning and the plan's apart; a refusal from either is in the
        first. Up to M3 these were ohsradio/guard.py licence_check and
        plan_check over this repository's own tables; ohs-libs'
        test_conformance.py proves the dataset answers as they did, bar
        the listed intended differences (docs/RELEASE-NOTES-beta.md)."""
        s = self.st
        chosen = s.get("plan", plans.AUTO)
        v = txguard.GUARD.check(txguard.profile(s), lo, hi, mode=mode, pep=pep, gain=gain, measured=measured,
                                plan="" if chosen in ("", plans.AUTO) else chosen,
                                plan_guard=s["planGuard"] if plan_guard is None else plan_guard, signal_bw=width)
        lic = guard.Verdict(refused=v.refused, warning=v.warning, limit_w=v.limit_w, limit_kind=v.limit_kind,
                            segment=v.segment)
        return lic, guard.Verdict(warning=v.plan_warning, segment=v.segment)

    def _licence(self, lo: float, hi: float, pep: float | None, gain: float, measured: bool = False,
                 mode: str | None = None) -> "guard.Verdict":
        """The licence's verdict alone (the band plan's guard off; its
        reserved segments still refuse)."""
        return self._judge(lo, hi, pep, gain, measured=measured, mode=mode, plan_guard="off")[0]

    # ------------------------------------------------------------------ helpers
    def _kind(self) -> str:
        return self.dev.kind if self.dev is not None else self.cfg.get("device", "sim")

    def converter_for(self, band: str, rx: bool = False) -> cv.Converter | None:
        """The converter band `band` is worked through (None: directly);
        with `rx`, the one it is received through (a TX-only one is not)."""
        return (xvtr.rx_for_band if rx else xvtr.for_band)(self.st, band)

    def _conv_at(self, f: float, st: dict | None = None, rx: bool = False) -> cv.Converter | None:
        """The converter on-air `f` goes through. Transmit's by default and
        receive's only when asked: a TX-only converter is in the first and
        not the second, and a transmit caller that forgot to say which would
        otherwise see no converter at all - and no drive cap."""
        b = bands.band_at(f)
        if b is None:
            return None
        return (xvtr.rx_for_band if rx else xvtr.for_band)(st or self.st, b.name)

    @staticmethod
    def _air_range(rng: tuple[float, float], conv: cv.Converter | None, tx: bool = False) -> tuple[float, float]:
        """A device's range as on-air frequencies through `conv`."""
        if conv is None:
            return rng
        lo, hi = conv.air_range(rng[0], rng[1], tx)
        return max(lo, 0.0), hi

    def _device_full_w(self, f: float, conv=_BAND) -> float:
        """The device's output at full drive for on-air `f`: at the
        converter's IF when the band has one - the HL2's 5 W at 28 MHz for 2 m,
        not its nothing at 144 MHz. `conv` overrides the band's converter
        (an over in progress goes through the one it keyed with)."""
        if conv is _BAND:
            conv = self._conv_at(f)
        f = conv.radio(f, tx=True) if conv is not None else f
        if self.dev is not None:
            w = self.dev.tx_full_w(f)
            if w > 0:
                return w
        kind = self._kind()
        if kind == "sim":
            return 5.0 if f < 30e6 else 0.0045
        return DEVICE_FULL_W.get(kind, 0.0)

    def _drive_limit(self, dial: float, conv=_BAND) -> tuple[float, str]:
        """The most drive (0..1) that keeps the input of the converter in
        front of on-air `dial` at or under its most drive, and the sentence
        if nothing may be transmitted through it at all ('' if it may).
        1.0 when the band is worked directly. The one place the cap is
        worked out, for the slider's ceiling, the guard and the device."""
        if conv is _BAND:
            conv = self._conv_at(dial)
        if conv is None:
            return 1.0, ""
        if not conv.transmits:
            return 0.0, f"{conv.title} is receive only: nothing may be transmitted through it"
        if conv.max_drive_dbm is None:
            return 0.0, f"Enter {conv.title}'s most drive (Settings › Converters) before transmitting through it"
        # Against the higher of the device's own figure and the output the
        # operator measured and entered for the band (devW): whichever makes
        # the cap stricter. The estimate prefers the measurement; the cap
        # must not, because a measurement below nominal would loosen it -
        # and the first version used only the nominal, so a Pluto measured
        # at +9 dBm into a -10 dBm transverter was over-driven by 2.5 dB.
        b = bands.band_at(dial)
        measured = power.chain(self.st["bandPower"], b.name if b else "").get("devW") or 0.0
        full = max(self._device_full_w(dial, conv), measured)
        if not (math.isfinite(full) and full > 0):
            # A device that does not say what it puts out (Soapy) cannot be
            # held under anything: refuse rather than assume it is small.
            band = f" for {b.name}" if b is not None else ""
            return 0.0, (f"The {self._kind()}'s output at {guard.mhz(conv.radio(dial, True))} MHz is not known, so "
                         f"the drive into {conv.title} cannot be held under its most drive: enter the radio's "
                         f"measured output{band} (Settings › Bands & power) to transmit through it")
        return cv.drive_cap(conv, full), ""

    @staticmethod
    def _power_unknown(c: dict, conv: cv.Converter | None) -> str:
        """The sentence when the power estimate cannot mean anything: through
        a transmitting converter with no gain entered for it, the estimate is
        the radio's milliwatts while the transverter puts out watts, and a
        low figure next to a licence limit reads as reassurance. A warning
        only: whether an unknown power should refuse is Brian's call on the
        power advisory (05/10/2026), not this check's."""
        if conv is None or not conv.transmits or c.get("paGainDb", 0.0) != 0.0:
            return ""
        return (f"Power estimate unknown: transverter output not entered. Enter {conv.title}'s gain as PA gain "
                f"(Settings › Bands & power)")

    def _hl2_pa_on(self) -> bool:
        """Whether the HL2's power amplifier may be on: the saved setting or
        the running radio's own state, whichever says on. The setting takes
        effect only on a restart, so saving it off leaves the PA on until
        then - and judging the setting alone let a transverter that takes
        0 dBm be keyed behind a PA that was still on."""
        running = bool(getattr(self.dev, "pa", False)) if self.dev is not None else False
        return bool(self.cfg.get("hl2Pa", True)) or running

    def _measured_here(self, c: dict, conv: cv.Converter | None = None) -> bool:
        """Whether the licence's power limit is enforced on a measurement on
        this band: the radio reports forward power, and no PA gain was
        entered. With a PA after it, the radio's sensor sees the PA's input;
        the antenna power is then the reading times an entered gain - an
        estimate again - so it only warns, until a PA's own sensor can be
        read (DESIGN-HAM section 6, rule 6, "later"). Through a converter
        the sensor sees the transverter's input, never the antenna."""
        return self._kind() in MEASURING and c.get("paGainDb", 0.0) == 0.0 and conv is None

    def _ranges(self):
        if self.dev is not None:
            return self.dev.rx_range, self.dev.tx_range
        return (0.0, 6e9), (0.0, 6e9)

    def _fs(self) -> float:
        if self.dev is not None:
            return self.dev.fs
        if self.cfg.get("device") == "hl2":
            return float(self.cfg.get("hl2Rate", 192_000))
        return float(self.cfg.get("sampleRate", 1_200_000))

    def _dev_freq(self, rf: float, conv: cv.Converter | None = None, tx: bool = False) -> float:
        """What to command a device to so that it really tunes `rf`: through
        `conv`, its IF; the device's reference error applies to what the
        device itself tunes."""
        f = conv.radio(rf, tx) if conv is not None else rf
        return f / (1.0 + self.st["ppm"] * 1e-6)

    def shift(self, s: dict, f: float) -> float:
        if s["mode"] != "fm":
            return 0.0
        how = s["rptShift"]
        if how == "auto":
            return bands.auto_shift(f, self._repeaters()[0])
        if how == "minus":
            return -s["rptOffsetHz"]
        if how == "plus":
            return s["rptOffsetHz"]
        return 0.0

    # ------------------------------------------------------------------ dials
    def _rx_dial(self, s: dict) -> float:
        f = s["vfo"] + (s["rit"] if s["ritOn"] else 0.0)
        if s["mode"] == "fm" and s["rptReverse"]:
            f += self.shift(s, s["vfo"])
        return f

    def _tx_dial(self, s: dict) -> float:
        base = s["txVfo"] if s["split"] else s["vfo"]
        if not s["rptReverse"]:
            base += self.shift(s, base)
        return base + (s["xit"] if s["xitOn"] else 0.0)

    # ------------------------------------------------------------------ state
    def _derive(self):
        super()._derive()
        self._licence_warnings(self.st.get("licenceInfo") or {})

    def _licence_warnings(self, info: dict) -> None:
        """The licence guard's warnings - not its refusals - as the transmit
        card's standing warning (Engine.tx_warn), for as long as the dial,
        mode and drive give them, keyed or not: the operator sees one before
        keying, not only after. A refusal stays the guard's: txBlocked, the
        licence chip, and "Not transmitting: ..." when PTT is pressed. The
        licence's power outranks the band plan when both apply."""
        unknown = info.get("powerUnknown") or ""
        if unknown:
            self.tx_warn("power", f"{unknown}. Transmitting is not refused: check the output with a power meter.",
                         "warn", priority=2, detail=unknown)
        elif info.get("powerWarning"):
            held = ("The measured output is held to the limit here." if info.get("measured") else
                    "Nothing measures the output here: check it with a power meter.")
            self.tx_warn("power", f"Estimate over the licence limit: transmitting is not refused. {held}",
                         "warn", priority=2, detail=info["powerWarning"])
        else:
            self.tx_clear("power")
        if info.get("planWarning"):
            self.tx_warn("plan", f"{info['planWarning']}. Transmitting is not refused: the band-plan guard is set "
                                 "to warn.", "warn", priority=1)
        else:
            self.tx_clear("plan")

    def _derived(self, rx_dial: float, tx_dial: float) -> dict:
        s = self.st
        # The power chain, the converter and the drive limit are the
        # transmit dial's: they say what reaches the antenna, and the
        # transverter's input, when it keys. Up to the converter review
        # (07/10/2026) they were the receive dial's, so a split transmit
        # dial in a transverter's band - receiving on 20 m, transmitting
        # on 2 m through a 0 dBm transverter - left the slider at 100 %.
        b = bands.band_at(s["vfo"])
        tb = bands.band_at(tx_dial)
        c = power.chain(s["bandPower"], tb.name if tb else "")
        conv = xvtr.for_band(s, tb.name) if tb is not None else None
        dev_full = self._device_full_w(tx_dial)
        full = power.full_pep(c, dev_full)
        est = full * (s["drive"] * power.envelope_peak(s["mode"])) ** 2
        lo, hi = self._occupied(s["mode"], tx_dial)
        lic, pl = self._judge(lo, hi, est, c["antGainDbi"], mode=s["mode"], width=self._width(s["mode"], None))
        plan = self._plan()
        # Only the band's ceiling holds the slider now. It used to stop at the
        # drive where the estimate met the licence too, which was a refusal
        # by estimate in all but name.
        max_drive = c["ceiling"]
        # Through a transmitting converter, also the drive at which the
        # device's output meets the converter's most drive (ohsradio/xvtr.py).
        # A converter nothing may go through (receive only, or no figure)
        # leaves the slider alone: the guard refuses with the reason, and
        # visiting the band does not throw the operator's drive away.
        cap, why_not = self._drive_limit(tx_dial, conv)
        if not why_not:
            max_drive = min(max_drive, cap)
        level = "refused" if (lic.refused or pl.refused) else ("warn" if (lic.warning or pl.warning) else "ok")
        why = lic.refused or pl.refused or " · ".join(w for w in (lic.warning, pl.warning) if w)
        dfr = xvtr.deferred(s, tb) if tb is not None else ""
        if dfr:
            # The licence may well allow it (6 m), but the guard refuses a
            # band no radio here covers; the chip must not say otherwise.
            level, why = "refused", dfr
        inf = self.licence_in_force()
        info = {"class": licences.class_name(inf.regime, inf.cls) if inf.cls else "",
                "regime": inf.regime_id if inf.regime is not None else "", "regimeShort": getattr(inf.regime, "SHORT", ""),
                "limitW": lic.limit_w, "limitKind": lic.limit_kind, "segment": pl.segment,
                "level": level, "why": why, "estimate": True, "powerWarning": lic.warning,
                "planWarning": pl.warning, "measured": self._measured_here(c, conv),
                "fullW": full, "deferred": dfr, "powerUnknown": self._power_unknown(c, conv)}
        rx_conv = self._conv_at(rx_dial, rx=True)
        seg = plan.segment_at(rx_dial)
        return {"band": b.name if b else "", "shift": self.shift(s, s["txVfo"] if s["split"] else s["vfo"]),
                "channel": (bands.channel_name(s["vfo"], self._repeaters()[0], getattr(plan, "SIMPLEX", []))
                            if s["mode"] == "fm" else ""),
                "segment": seg.label if seg else "", "licenceInfo": info, "estPep": est, "planInUse": plan.ID,
                "converter": rx_conv.title if rx_conv is not None else "",
                "radioFreq": rx_conv.radio(rx_dial) if rx_conv is not None else rx_dial,
                "maxDrive": math.floor(max_drive * 1e4) / 1e4}      # never rounded up past the limit

    def _adjust_set(self, clean: dict) -> None:
        merged = {**self.st, **clean}
        if any(k in clean for k in ("converters", "bandConverters")):
            xvtr.check(merged)
        if "vfo" in clean and self.dev is not None and self.running:
            lo, hi = self.dev.rx_range
            conv = self._conv_at(clean["vfo"], merged, rx=True)
            f = conv.radio(clean["vfo"]) if conv is not None else clean["vfo"]
            if not lo <= f <= hi:
                # One whole sentence with the converter and one without,
                # rather than a translated "through" clause spliced in.
                if conv is not None:
                    said = _("The {device} receives {lo}-{hi} MHz; {mhz} MHz ({radio} MHz through {converter}) "
                             "is outside it")
                else:
                    said = _("The {device} receives {lo}-{hi} MHz; {mhz} MHz is outside it")
                raise ValueError(said.format(device=self._kind(), lo=guard.mhz(lo), hi=guard.mhz(hi),
                                             mhz=guard.mhz(clean["vfo"]), radio=guard.mhz(f),
                                             converter=conv.title if conv is not None else ""))
        # Arriving in another band brings that band's usual repeater split
        # with it - the plan in force's, or the station country's
        # (plans/repeaters.py): 600 kHz is never right on 70 cm. A band-stack
        # register that remembers its own (an RBW repeater's 5 MHz) sends it
        # in the same set(), and wins.
        if "vfo" in clean and "rptOffsetHz" not in clean:
            new_b, old_b = bands.band_at(clean["vfo"]), bands.band_at(self.st["vfo"])
            offset = self._repeaters()[1].get(new_b.name) if new_b is not None else None
            if new_b is not None and new_b is not old_b and offset:
                clean["rptOffsetHz"] = float(offset)
        # A new band (or a lower ceiling) may lower maxDrive: an explicit drive
        # in the same set() is judged against the new one in _after_set.
        if "drive" in clean and clean["drive"] > self.st["maxDrive"] and any(
                k in clean for k in self.TX_DIAL_KEYS + ("bandPower", "licenceClass", "converters",
                                                         "bandConverters")):
            self._drive_wanted = clean.pop("drive")

    def _after_set(self, changed: dict) -> None:
        s = self.st
        if any(k in changed for k in self.LICENCE_KEYS + ("plan",)):
            self._refresh_presets()
        wanted = getattr(self, "_drive_wanted", None)
        self._drive_wanted = None
        if wanted is not None or s["drive"] > s["maxDrive"] + 1e-9:
            new = min(s["maxDrive"], wanted if wanted is not None else s["drive"])
            if abs(new - s["drive"]) > 1e-9:
                with self.lock:
                    s["drive"] = new
                    self.cfg["drive"] = new
                    self.dirty = True
                    self.pending["drive"] = new
                if wanted is None:
                    self.toast(_("Drive lowered to {percent:.0f} %: this band's ceiling").format(percent=new * 100),
                               "info")
                self._derive()                    # the estimate follows the new drive
            if s["keyed"] and self.dev is not None:
                self._drive_device(self.dev, self._over_drive())
        elif "drive" in changed and s["keyed"] and self.dev is not None:
            self._drive_device(self.dev, self._over_drive())
        if self.running and any(k in changed for k in ("vfo", "rit", "ritOn", "rptReverse", "rptShift", "mode",
                                                       "rptOffsetHz")):
            self._maybe_recentre()
        if any(k in changed for k in ("seqDelayMs",)) and self.seq is not None:
            self.seq.delay = s["seqDelayMs"] / 1000.0

    def _maybe_recentre(self):
        rx = self._rx_dial(self.st)
        fs = self._fs()
        half = USABLE * fs / 2
        pending = self.pending_centre is not None
        c = self.pending_centre if pending else self.centre
        b = bands.band_at(rx)
        conv = self._conv_at(rx, rx=True)
        rr = self._air_range(self._ranges()[0], conv)
        want = plan_centre(rx, b, fs, rr)
        # A band the span holds whole has one centre whatever the dial: snap to it.
        band_based = b is not None and plan_centre(b.lo, b, fs, rr) == plan_centre(b.hi, b, fs, rr) == want
        # Into or out of a converter's band, the device retunes whatever the centre.
        other = conv != (self.pending_conv if pending else self.rx_conv)
        if c is None or other or not (c - half + 3_000 <= rx <= c + half - 3_000) or (band_based and c != want):
            self.pending_conv = conv
            self.pending_centre = want

    # --------------------------------------------------------------- lifecycle
    def _start_consumers(self) -> None:
        g = self.geo
        self.fm_d = g.decimation_for(FM_RATE)
        self.fm_ch = None
        self.fm_cut = None
        self.fmdemod = FmDemod(g.fs / self.fm_d)
        self.fm_mod = FmMod(g.fs / self.fm_d)
        self.am_mod = AmMod()
        self.tx_src24 = Source(g, self.fm_d)
        try:
            out = make_output(self.cfg)
        except SequencerError as e:
            self.toast(_("{error}. Transmit will be refused until it is fixed.").format(error=e), "error")
            out = None
        self.seq_error = "" if out is not None else _("The PTT sequencer's output could not be opened (Settings)")
        self.seq = Sequencer(out, self.st["seqDelayMs"], on_state=lambda st_: self._status(seqState=st_)) \
            if out is not None else None

    def _initial_tuning(self) -> float:
        fs = self.dev.fs
        rx = self._rx_dial(self.st)
        self._use_rx_conv(self._conv_at(rx, rx=True))
        self.centre = plan_centre(rx, bands.band_at(rx), fs, self._air_range(self.dev.rx_range, self.rx_conv))
        self.pending_centre = None
        self.settle_at = 0          # rx_samples counts from 0 again on every start
        return self._dev_freq(self.centre, self.rx_conv)

    def _use_rx_conv(self, conv: cv.Converter | None) -> None:
        """The receiver now works through `conv` (on the receive thread, or
        before it starts): mirror the IQ for an inverting one, and put the
        same converter in front of the simulator, which then hears the air
        through it as the radio would."""
        self.rx_conv = conv
        self.rx_invert = bool(conv is not None and conv.inverted)
        fn = getattr(self.dev, "set_rx_converter", None)
        if fn is not None:
            fn(conv)

    def _start_status(self) -> dict:
        lo, hi = self.wide_span()
        return {"spanLo": lo, "spanHi": hi, "seqState": "rx", "swr": 0.0, "fwdW": 0.0}

    def _mode_caps(self, info: dict) -> dict:
        info = dict(info)
        if "am" in info:
            info["am"] = dict(info["am"], encode=True)
        return info

    def stop(self) -> None:
        super().stop()
        self._cwskim_enable(False)
        if self.seq is not None:
            self.seq.close()
            self.seq = None

    # ------------------------------------------------------------- frequencies
    def _off(self, dial: float) -> float:
        return dial - self.centre

    def _dial_at(self, off: float) -> float:
        return off + self.centre

    def wide_span(self) -> tuple[float, float]:
        half = USABLE * self.geo.fs / 2
        return self.centre - half, self.centre + half

    def _rec_extra(self, s: dict) -> dict:
        conv = self.rx_conv
        out = {"converter": conv.to_dict() if conv is not None else None, "band": s.get("band"),
               "ppm": s.get("ppm")}
        if self._kind() == "hl2":
            out["hl2Lna"] = s.get("hl2Lna")
        return out

    # ------------------------------------------------------------------ receive
    def _configure_rx(self):
        # The HL2's LNA is its only receive gain, so it gets what NB's
        # rxGain got: applied on the rx thread between reads whenever a
        # save changes it. It used to reach the radio only when it was next
        # opened, while the S-meter's calibration (smeter.known_gain) took
        # the new figure from the moment of saving - so the meter was
        # wrong by the difference until Radio > Restart. The device's own
        # lna_db is the record of what it was last sent: it survives a
        # reconnect, so no separate "applied" copy can drift from it.
        super()._configure_rx()
        want = float(self.st["hl2Lna"])
        have = getattr(self.dev, "lna_db", None)
        if have is not None and have != want:
            self.dev.set_lna(want)

    def _configure_consumers(self, s: dict) -> None:
        cut = s["fmDeviation"] + 5_000.0
        if self.fm_ch is None or cut != self.fm_cut:
            self.fm_ch = Channel(self.geo, self.fm_d, cutoff=min(cut, self.geo.fs / self.fm_d * 0.45))
            self.fm_cut = cut
        self.fmdemod.configure(s["fmDeviation"], s["sqlLevel"], s["ctcssRx"])
        self._cwskim_enable(bool(s["cwSkim"]) and self.running)
        cw = self.cwskim
        if cw is not None:
            cw.configure(s)

    # -------------------------------------------------------------- CW skimmer
    def _cwskim_enable(self, on: bool) -> None:
        """Start or stop the CW skimmer (cwskim.py), as NB's _skim_enable
        does its band skimmer. It rides the receive claim the radio already
        holds: no device of its own, and it never retunes."""
        if on and self.cwskim is None:
            self.cwskim = CwSkim(self, mode=self.CWSKIM_MODE)
            self.cwskim.start()
        elif not on and self.cwskim is not None:
            cw, self.cwskim = self.cwskim, None
            cw.stop()

    def _rx_monitor(self, X, starts, t_stream: float) -> None:
        cw = self.cwskim     # read once: stop() may clear it from another thread
        if cw is not None:
            cw.feed(X, starts)

    def cwskim_view(self) -> dict:
        """GET api/cwskim (docs/SERVER-API.md)."""
        cw = self.cwskim
        return cw.view() if cw is not None else dict(off_item(), spots=[])

    def _demodulate(self, X, starts, rx_dial: float):
        if self.st["mode"] != "fm":
            return super()._demodulate(X, starts, rx_dial)
        self.fm_ch.set_freq(self._off(rx_dial))
        audio, level = self.fmdemod(self.fm_ch.take(X, starts))
        tone = self.fmdemod.tone
        if tone != self.ctcss_heard:
            self.ctcss_heard = tone
            self._emit_event({"mode": "fm", "ctcss": tone})
        self._status(ctcssHeard=tone, sqlOpen=bool(self.fmdemod.open))
        return audio, level

    def _rx_audio_gain(self, s: dict) -> float:
        return 0.0 if s["keyed"] else 1.0           # half duplex

    def _rx_done(self, s: dict) -> None:
        c = self.pending_centre
        if c is not None:
            self.pending_centre = None
            self._use_rx_conv(self.pending_conv)
            self.centre = c
            self.rx_if = self._dev_freq(c, self.rx_conv)
            self.dev.set_rx_if(self.rx_if)
            self.settle_at = self.rx_samples + int(RETUNE_SETTLE * self.geo.fs)
            lo, hi = self.wide_span()
            self._status(spanLo=lo, spanHi=hi)

    def _rx_settled(self) -> bool:
        # Between a dial change that leaves the span and the end of the
        # block that applies the new centre, the channel is still taken
        # from the old one (where the dial may be off the edge); after it,
        # samples the radio took before it moved are still in its buffers
        # and in the analysis bank's overlap.
        return self.pending_centre is None and self.rx_samples >= self.settle_at

    def _meter_extra(self, s: dict) -> dict:
        return {"fwd": s["fwdW"], "swr": s["swr"], "paTemp": s["paTemp"], "seq": s["seqState"],
                "sql": s["sqlOpen"], "estPep": s["estPep"]}

    # -------------------------------------------------------------- operating
    def start_on(self, band: str | None = None, rf: float | None = None, mode: str | None = None) -> None:
        """The command line's --band, --rf (MHz) and --mode, for the window
        and headless alike. The mode goes first: since 0.1.18 a band's
        first visit lands where the mode in use belongs (bands.first_register),
        so "--band 20m --mode ft8" applied band-first landed 20 m on the SSB
        segment and then switched to FT8 there, where no FT8 is - the HAM
        0.1.18 Windows build's own smoke test decoded nothing and stopped the
        release. Then the band, then --rf, and the mode once more only if the
        band's register changed it (from CW, a first visit lands in the SSB
        segment in USB, and the operator asked for CW)."""
        if mode:
            self.set(mode=mode)
        if band:
            self.band(band)
        if rf:
            self.set(vfo=rf * 1e6)
        if mode and self.state()["mode"] != mode:
            self.set(mode=mode)

    def band(self, name: str) -> dict:
        """Go to band `name` at its last-used register; if already there,
        step to its next register (the band button's second press)."""
        b = bands.BY_NAME.get(name)
        if b is None:
            raise ValueError(_("There is no band called {name}").format(name=repr(name)))
        dfr = xvtr.deferred(self.st, b)
        if dfr:
            raise ValueError(dfr)
        s = self.state()
        stacks = {k: {"i": v["i"], "regs": [dict(r) for r in v["regs"]]} for k, v in s["bandStacks"].items()}
        cur = bands.band_at(s["vfo"])
        reg = {"vfo": s["vfo"], "mode": s["mode"], **{k: s[k] for k in bands.STACK_KEYS}}
        # A band never visited is seeded from the mode the operator is in
        # as they press it (bands.first_register): the FT8 dial from a
        # digital mode, the plan in force's SSB segment from anything else.
        seed = {"mode": s["mode"], "plan": self._plan()}
        if cur is not None:
            e = stacks.setdefault(cur.name, {"i": 0, "regs": bands.seed_stack(cur, **seed)})
            e["regs"][e["i"] % len(e["regs"])] = reg
        e = stacks.setdefault(b.name, {"i": 0, "regs": bands.seed_stack(b, **seed)})
        if cur is not None and cur.name == b.name:
            e["i"] = (e["i"] + 1) % len(e["regs"])
        r = e["regs"][e["i"] % len(e["regs"])]
        changes = {"vfo": r["vfo"], "mode": r["mode"], "bandStacks": stacks, "split": False, "rptReverse": False}
        for k in bands.STACK_KEYS:
            if k in r:
                changes[k] = r[k]
        return self.set(**changes)

    def store_stack(self) -> None:
        """Remember the current dial in the current band's register."""
        s = self.state()
        cur = bands.band_at(s["vfo"])
        if cur is None:
            return
        stacks = {k: {"i": v["i"], "regs": [dict(r) for r in v["regs"]]} for k, v in s["bandStacks"].items()}
        e = stacks.setdefault(cur.name, {"i": 0, "regs": bands.seed_stack(cur, s["mode"], self._plan())})
        e["regs"][e["i"] % len(e["regs"])] = {"vfo": s["vfo"], "mode": s["mode"]}
        self.set(bandStacks=stacks)

    def toneburst(self) -> None:
        """1750 Hz for toneburstMs: added to the over if keyed in FM, else
        sent on its own (it keys, and the guard applies, like any send)."""
        self.heartbeat()
        s = self.st
        if s["mode"] != "fm":
            raise ValueError(_("A toneburst is an FM thing: switch to FM first"))
        secs = s["toneburstMs"] / 1000.0
        if s["keyed"]:
            self.fm_mod.toneburst(secs)
            return
        n = int(secs * AUDIO_RATE) + int(0.1 * AUDIO_RATE)
        req = {"source": "toneburst", "mode": "fm", "audio": np.zeros(n, np.float32), "burst": secs}
        req["occupied_dial"] = self._tx_dial(s)
        req["occupied"] = self._occupied("fm", req["occupied_dial"])
        self._key(req)

    def tune(self, on: bool) -> None:
        """A steady carrier at tuneDrive times the current drive, for an ATU
        or a PA's tune; the guard applies as for any key-up. A share of
        the drive rather than of the band's ceiling, because drive is
        already held under both the ceiling and the licence limit: the
        tune carrier can never be more than the operator's own setting."""
        self.heartbeat()
        if not on:
            self._release()
            return
        if self.st["keyed"]:
            return
        self._key({"source": "tune", "mode": "cw", "audio": None, "tune": True})

    def ack_swr(self) -> None:
        """The operator has seen the SWR trip; keying is allowed again."""
        self._status(swrTripped=False)
        self._derive()

    # ------------------------------------------------------------------ transmit
    def _occupied(self, mode: str, dial: float, audio=None):
        s = self.st
        if mode == "fm":
            w = s["fmDeviation"] + 3_000.0          # Carson's rule, 3 kHz audio
            return dial - w, dial + w
        if mode == "am":
            return dial - s["txFilterHi"], dial + s["txFilterHi"]
        return super()._occupied(mode, dial, audio)

    def _width(self, mode: str, occupied) -> float | None:
        """One signal's width for the band plan's bandwidth limits: measured
        (send() passes the rendered audio's occupied band), else typical."""
        if occupied is not None:
            return occupied[1] - occupied[0]
        return guard.SIGNAL_WIDTH.get(mode)

    def _tx_guard(self, mode: str, dial: float, occupied, req: dict | None = None) -> str:
        s = self.st
        b = bands.band_at(dial)
        dfr = xvtr.deferred(s, b) if b is not None else ""
        if dfr:
            return dfr
        tc = xvtr.for_band(s, b.name) if b is not None else None
        why = xvtr.tx_problem(s, b.name, self._kind(), self._hl2_pa_on()) if b is not None else ""
        if why:
            return why
        lo, hi = occupied or self._occupied(mode, dial)
        _, txr = self._ranges()
        # The device's range is the radio's: through a converter, the IF.
        r_lo, r_hi = tc.radio_range(lo, hi, tx=True) if tc is not None else (lo, hi)
        if not (txr[0] <= r_lo and r_hi <= txr[1]):
            via = f" ({guard.mhz(tc.radio(dial, True))} MHz through {tc.title})" if tc is not None else ""
            return f"The {self._kind()} cannot transmit on {guard.mhz(dial)} MHz{via}"
        if self.seq is None:
            return self.seq_error or "The PTT sequencer is not ready"
        if s.get("swrTripped"):
            return "Unkeyed earlier on high SWR: check the antenna, then acknowledge it on the transmit card"
        c = power.chain(s["bandPower"], b.name if b else "")
        drive = s["drive"] * (s["tuneDrive"] if req and req.get("tune") else 1.0)
        if tc is not None:
            # maxDrive holds the slider there already; this is the last word
            # at key-up, on the device's figure for this IF.
            cap, why = self._drive_limit(dial, tc)
            if why:
                return why
            if drive > cap + 1e-9:
                return (f"Drive {drive * 100:.1f} % would put more than {tc.max_drive_dbm:g} dBm into {tc.title} "
                        f"(its most drive): {cap * 100:.1f} % at most")
        est = power.pep(c, self._device_full_w(dial), drive, mode)
        lic, _pl = self._judge(lo, hi, est, c["antGainDbi"], mode=mode, width=self._width(mode, occupied))
        return lic.refused

    def _tx_chain(self, req: dict):
        s = self.st
        mode = req["mode"]
        if mode == "fm":
            self.fm_mod.configure(s["fmDeviation"], s["ctcssTx"], s["ctcssLevel"], s["micGain"],
                                  voice=self._voice_over(req))
            if req.get("burst"):
                self.fm_mod.toneburst(req["burst"])
            return self.fm_mod, self.tx_src24
        if mode == "am":
            self.am_mod.configure(s["txFilterHi"], s["micGain"], voice=self._voice_over(req), lo=s["txFilterLo"])
            return self.am_mod, self.tx_src
        return super()._tx_chain(req)

    def _tx_key_up(self, dev) -> None:
        s = self.st
        req = self.tx_req or {}
        if self.seq is None:
            raise TxRefused(self.seq_error)
        target = s["txDial"]
        self._use_tx_conv(self._conv_at(target))
        # The guard ran when the over was keyed, which for FT8 is up to a
        # slot earlier, and the sequencer waits again below. Judge it again
        # on the converter just picked, and once more as the device keys,
        # so what goes out is what was judged.
        self._judge_again(req, target)
        lo = self._tx_lo_for(dev, target)
        self.tx_lo = lo
        self.swr_avg = None
        dev.set_drive(0.0)
        # The hook for per-converter sequencer outputs (a transverter's own
        # PTT line, DESIGN-HAM section 6.1 "profiles per band/transverter"):
        # the sequencer is told which converter this over goes through
        # before it keys anything. It has one output today.
        self.seq.use(self.tx_conv)
        if not self.seq.key_up(lambda: bool(self.st["keyed"])):
            raise TxRefused("Keying was cancelled during the PTT sequence")
        dev.set_tx_freq(self._dev_freq(lo, self.tx_conv, tx=True))
        self.tx_src.freq = self.tx_src24.freq = target - lo
        self._judge_again(req, target)
        dev.tx_start()
        self._drive_device(dev, self._over_drive(req))
        self.over_count = 0
        # The power and band-plan warnings are on the transmit card already
        # (_derive). Up to 0.1.9 each was toasted again here, at every
        # key-up, so a run of FT8 overs stacked the same three toasts.

    def _over_drive(self, req: dict | None = None) -> float:
        """The drive this over runs at: the operator's, or Tune's share of it.
        Key-up applied the share and a drive changed mid-tune did not, so
        moving the slider during a 20 % tune carrier made it the full 80 %."""
        req = req if req is not None else (self.tx_req or {})
        return self.st["drive"] * (self.st["tuneDrive"] if req.get("tune") else 1.0)

    def _judge_again(self, req: dict, target: float) -> None:
        """TxRefused unless the over may still go: the guard passes and the
        converter it would go through is still the one it was set up for."""
        if self._conv_at(target) != self.tx_conv:
            raise TxRefused("the converter for the transmit dial changed while the over was being keyed")
        why = self._tx_blocked(self._occupied_now(req), req)
        if why:
            raise TxRefused(why)

    def _drive_device(self, dev, drive: float) -> None:
        """Every drive HAM gives a device while keyed comes through here, and
        is held under the most drive of the converter the over goes out
        through - and of the one the settings now give its transmit dial,
        should they differ. maxDrive, the drive rule and the guard should
        each already have stopped anything higher; this is the last word,
        because a path that misses all three (the split that once did) must
        still not put a radio's watts into a 0 dBm input."""
        dial = self.st["txDial"]
        cap = 1.0
        for conv in {self.tx_conv, self._conv_at(dial)}:
            if conv is not None:
                cap = min(cap, self._drive_limit(dial, conv)[0])
        if drive > cap + 1e-12:
            self.log.warning("drive %.4f held to %.4f at the device: over the converter's most drive", drive, cap)
            drive = cap
        dev.set_drive(drive)

    def _on_keyed(self) -> dict:
        return {"seqState": "tx"}

    @staticmethod
    def _tx_offset(dev) -> float:
        """Where the signal sits above the TX LO: a quarter of the rate for an
        analogue LO that leaks (the Pluto), what the device says otherwise
        (the HL2's NCO: on it)."""
        off = getattr(dev, "tx_offset_hz", None)
        return TX_OFFSET * dev.fs if off is None else float(off)

    def _tx_lo_for(self, dev, target: float) -> float:
        lo, hi = self._air_range(dev.tx_range, self.tx_conv, tx=True)
        return max(lo, min(hi, target - self._tx_offset(dev)))

    def _use_tx_conv(self, conv: cv.Converter | None) -> None:
        """This over goes out through `conv` (on the transmit thread)."""
        self.tx_conv = conv
        self.tx_invert = bool(conv is not None and conv.inverted)
        fn = getattr(self.dev, "set_tx_converter", None)
        if fn is not None:
            fn(conv)

    def _tx_follow(self, dev) -> bool:
        s = self.st
        target = s["txDial"]
        if self._conv_at(target) != self.tx_conv:
            # Into another converter's band (or out of one) mid-over: the
            # radio's output is wired for one of them only.
            self._unkey("Unkeyed: the transmit dial moved to a band with another converter", "warn")
            return False
        reach = getattr(dev, "tx_reach_hz", None) or TX_REACH * dev.fs
        off = self._tx_offset(dev)
        if abs(target - self.tx_lo) > reach or (off > 0 and target - self.tx_lo < 10_000):
            self.tx_lo = self._tx_lo_for(dev, target)
            dev.set_tx_freq(self._dev_freq(self.tx_lo, self.tx_conv, tx=True))
        self.tx_src.freq = self.tx_src24.freq = target - self.tx_lo
        return self._tx_protect(dev)

    def _tx_protect(self, dev) -> bool:
        """Measured SWR and PA temperature (design rule 7): unkey above the
        limits. SWR is averaged over ~0.3 s so SSB peaks do not trip it."""
        tel = dev.telemetry()
        if not tel:
            return True
        s = self.st
        fwd, rev, temp = tel.get("fwd"), tel.get("rev"), tel.get("temp")
        upd = {}
        if tel.get("tx_inhibit"):
            self._trip(f"Unkeyed: the {self._kind()}'s TX-inhibit input is active", "error")
            return False
        if temp is not None:
            upd["paTemp"] = float(temp)
            if temp > s["paTempLimit"]:
                self._status(**upd)
                self._trip(f"Unkeyed: PA temperature {temp:.0f} °C is above the {s['paTempLimit']:.0f} °C limit",
                            "error")
                return False
        if fwd is not None and not self._measured_ok(float(fwd)):
            upd["fwdW"] = float(fwd)
            self._status(**upd)
            return False
        if fwd is not None and rev is not None:
            upd["fwdW"] = float(fwd)
            min_fwd = min(SWR_MIN_FWD, 0.1 * self._device_full_w(s["txDial"]))
            if fwd >= min_fwd:
                g = math.sqrt(max(0.0, min(0.99, rev / max(fwd, 1e-12))))
                swr = (1 + g) / (1 - g)
                self.swr_avg = swr if self.swr_avg is None else 0.75 * self.swr_avg + 0.25 * swr
                upd["swr"] = round(self.swr_avg, 2)
                if self.swr_avg > s["swrLimit"]:
                    upd["swrTripped"] = True
                    self._status(**upd)
                    self._trip(f"Unkeyed: SWR {self.swr_avg:.1f}:1 is above the {s['swrLimit']:.1f}:1 limit - "
                                f"check the antenna and feeder", "error")
                    return False
        if upd:
            self._status(**upd)
        return True

    def _measured_ok(self, fwd: float) -> bool:
        """The licence's power limit on the measured forward power (rule 6):
        False, having unkeyed, after OVER_READINGS readings in a row over
        it - one stray reading does not end an over, a real excess ends it
        within a few blocks. The reading is taken as the power at the
        antenna, ignoring the entered feeder loss: an entered number may
        only make this check stricter, never looser."""
        s = self.st
        b = bands.band_at(s["txDial"])
        c = power.chain(s["bandPower"], b.name if b else "")
        if not self._measured_here(c, self.tx_conv):
            return True
        req = self.tx_req or {}
        lo, hi = self._occupied_now(req) or self._occupied(req.get("mode", s["mode"]), s["txDial"])
        v = self._licence(lo, hi, fwd, c["antGainDbi"], measured=True, mode=req.get("mode", s["mode"]))
        if not v.refused or v.limit_w is None:
            self.over_count = 0
            return True
        self.over_count += 1
        if self.over_count < OVER_READINGS:
            return True
        allowed = guard.max_pep_for(v.limit_kind, v.limit_w, c["antGainDbi"])
        drive = s["drive"] * (s["tuneDrive"] if req.get("tune") else 1.0)
        meet = drive * math.sqrt(allowed / fwd) if fwd > 0 else 0.0
        self._trip(f"Unkeyed: {v.refused}. Lower Drive (about {meet * 100:.0f} % meets it)", "error")
        return False

    def _trip(self, reason: str, level: str) -> None:
        """A protection unkeys: RF stops at once, no tail drained (an
        emergency unkey, ohscore/engine.py)."""
        self._unkey(reason, level)

    def _tx_draining(self, dev) -> bool:
        # SWR, PA temperature, TX inhibit and measured power still apply
        # while a normal end lets the device's queue go out.
        return self._tx_protect(dev)

    def _tx_key_down(self, dev) -> None:
        # The engine has already let the device's queue go out on a normal
        # end (Engine._tx_drain), so drive to zero here silences nothing
        # that was meant to be sent; on an emergency it silences the queue,
        # which is the point. Until HAM 0.1.6 this drained the HL2 itself
        # (up to 0.2 s) on Escape and the watchdog too, and nothing drained
        # the simulator or a Pluto at all.
        try:
            dev.set_drive(0.0)
        finally:
            try:
                dev.tx_stop()
            finally:
                if self.seq is not None:
                    self.seq.key_down()

    def _on_unkeyed(self) -> dict:
        return {"fwdW": 0.0, "seqState": "rx"}

    # ------------------------------------------------------- mode auto-tune
    def _mode_spots(self, mode: str) -> list[tuple[float, float, float]]:
        """This band's usual dial for `mode`, if the band plan has one -
        never another band's: a mode click only ever moves the dial
        within the band it is already in (Brian, 07/10/2026). FT8 and FT4
        are WSJT-X's own default dials (bands.py Band.ft8/ft4, cited
        there), JS8 JS8Call's (Band.js8); CW is the plan's own centre of activity
        (the plan in force's CENTRES; the RSGB's were checked line by line
        against its PDF in docs/ham/licence-check.md). Any other mode,
        or a band neither source has one for, gets nothing: picking it
        never retunes - PSK31/63/125, RTTY and SSTV have no agreed dial
        on these bands (docs/ham/bandplan-r1-uk.md: "unverified
        convention", or nothing at all), and Q65/WSPR are not offered as
        a mode click here."""
        b = bands.band_at(self.st["vfo"])
        if b is None:
            return []
        if mode == "ft8":
            targets = [b.ft8] if b.ft8 else []
        elif mode == "ft4":
            targets = [b.ft4] if b.ft4 else []
        elif mode == "js8":
            targets = [b.js8] if b.js8 else []
        elif mode == "cw":
            targets = [f for f, _lab, m in self._plan().CENTRES if m == "cw" and b.lo <= f <= b.hi]
        else:
            targets = []
        return [(t, t - MODE_TUNE_TOL, t + MODE_TUNE_TOL) for t in targets]

    # ----------------------------------------------------------- memories, log
    def save_memory(self, name: str, rf: float | None = None, mode: str | None = None) -> dict:
        return super().save_memory(name, rf, mode)

    def pad_actions(self):
        """What the pad does here (ohscore/padactions.py, ohsradio/pad-actions.json):
        the power knob is the drive, 2 % a detent; the band knob steps
        through the bands as the band bar orders them."""
        from ohscore.padactions import PadActions
        return PadActions(self, state.MODES, ("drive", 0.02, 0.0, 1.0), bands=[b.name for b in bands.BANDS])

    def _adif_fields(self, r: dict):
        b = bands.band_at(r["rf"])
        before = [("BAND", ADIF_BAND[b.name])] if b else []
        before.append(("FREQ", f"{r['rf'] / 1e6:.6f}"))
        return before, []
