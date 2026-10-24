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
  While a background decoder session runs, the centre is **pinned**
  instead (Brian, 23/10/2026; the "pinned span" section below): the dial
  moves inside the span, the centre stays, and a tune out of it is
  refused unless the operator lets it stop the sessions.
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
- **wide FM** (broadcast listening): its own 180 kHz channel of at least
  240 kS/s, refused on a receiver too slow to hold one (a Hermes-Lite 2
  below 384 kS/s), and never transmitted; heard in stereo with RDS
  through shack_sdr's receiver (ohscore/dsp/wfm.py StereoWfm), which
  starts again on every retune, its RDS in `rds` (state) and its stereo
  flag on the meter;
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
import threading
import time
from collections import deque

import numpy as np

from ohscore import converters as cv
from ohscore import licences, smeter_cal, txguard
from ohscore import span as spanfit
from ohscore.decoders import Refused, sessions_text
from ohscore.devices import DeviceError
from ohscore.i18n import fmt
from ohscore.dsp import wfm
from ohscore.dsp.bank import Channel, Geometry, Source
from ohscore.dsp.demod import passband
from ohscore.dsp.fm import FM_RATE, FmDemod, FmMod
from ohscore.dsp.mod import AmMod
from ohscore.engine import AUDIO_RATE, Engine, SpanPinned, TxRefused

from ohsradio.i18n import _

from . import bands, bcastgain, config, guard, notch, power, state, xvtr
from .bandscan import BandScanner, rds_text
from .cwskim import CwSkim, off_item
from .devices import REGISTRY
from . import plans
from .plans import repeaters
from .sequencer import Sequencer, SequencerError, make_output

# cwskim and cwspot: the CW skimmer (cwskim.py, docs/ENGINE-API.md); decoders:
# the decoder sessions' results (ohscore/decoders.py). Never in the
# server's default set, so a client gets them only when it asks.
# stations: a band scan's list changed (bandscan.py), likewise only when asked.
FEED_KINDS = ("wide", "zoom", "events", "meter", "state", "toast", "cwskim", "cwspot", "decoders", "stations")
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
# Receivers that mix straight to zero IF and so make a DC spike at the
# centre of every span (dcBlock auto). The HL2 samples the antenna and
# mixes digitally (no spike); the simulator makes none; a recording played
# back is a "file" and was kept raw, so auto leaves it as it was.
ZERO_IF = ("pluto", "libresdr", "rtlsdr", "sdrplay", "soapy")
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
    # Receive audio at 48 kHz (Engine.OUT_RATE): wide FM flat to 15 kHz and
    # room for stereo; the decoders and transmit stay at 12 kHz.
    OUT_RATE = 48_000
    REC_STATES = ("band",)
    # A DAB session takes the receiver (Engine.hold_receiver): Radio's
    # hardware follows its dial anyway, so it can be centred on a block.
    # The repeater offset goes back with the dial, because arriving back on
    # a band from Band III would otherwise reset it to the band's usual one
    # (_adjust_set).
    HOLDS_RECEIVER = True
    HELD_KEYS = Engine.HELD_KEYS + ("rptReverse", "rptShift")
    HOLD_PRIOR = Engine.HOLD_PRIOR + ("rptOffsetHz",)
    # Background decoder sessions pin the receiver's centre (pin_plan).
    PINS_SPAN = True
    # Every setting that moves the receive dial or widens what it hears:
    # what a pinned span judges (_pin_check).
    PIN_KEYS = ("vfo", "mode", "rit", "ritOn", "rptReverse", "rptShift", "rptOffsetHz")

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
        # The gain a broadcast station gets while it plays (bcastgain.py),
        # and the device's overload count when last looked at. Before the
        # engine's own set-up, which asks _rx_gain_wanted.
        self.bgain = bcastgain.Policy()
        self._bg_overloads = None
        # dabNotch auto's verdict (notch.DabAuto), the device's overload
        # count it last saw, and the notches the device last said it has.
        self.dab_auto = notch.DabAuto()
        self._notch_overloads = None
        self._notch_have: tuple = ()
        super().__init__(*a, **kw)
        self.centre = None
        self.pending_centre = None
        self.settle_at = 0          # rx_samples from which a re-centring has reached the channels
        self.tx_lo = None
        self.seq = None
        self.swr_avg = None
        self.ctcss_heard = 0.0
        self.wfm_ch = self.wfmdemod = None      # built at start when the rate allows (_start_consumers)
        # The receive dial wide FM last heard (None: start again before the
        # next block) and the RDS revision last published: the receive
        # thread's own, so a retune resets the receiver exactly once.
        self._wfm_dial: float | None = None
        self._rds_rev = -1
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
        # 3 s of 10 Hz meter readings, the "current reading" behind
        # Calibrate… and the API's {"dbm": ...} form (smeter_cal.average_dbfs).
        self._smeter_hist: deque = deque(maxlen=30)
        # The receiver's centre (and converter) before a hold took it, put
        # back exactly when it ends (_held_retune): the dial alone would
        # give a band-following centre that need not be the one it had.
        self._centre_before: tuple | None = None
        # The centre the background decoder sessions pinned (pin_to), None
        # while it follows the dial; and, per calling thread, what a set()
        # that passed _pin_check does to it once applied (_after_set).
        self.pin: float | None = None
        self._pin_tls = threading.local()
        # The weekly FM and DAB scan (bandscan.py), told of everything a
        # person does so it knows when the radio is idle.
        self.bandscan = BandScanner(self)
        self.activity_hooks.append(self.bandscan.touch)
        self.st["stationsAt"] = self.bandscan.stations_at()

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
        if clean.get("mode") == "wfm" and self.st["mode"] != "wfm":
            why = self._wfm_why()
            if why:
                raise ValueError(why)
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
            # The last station's RDS goes the moment the dial does, not a
            # block later: a client reading the state after its own set()
            # must never see the old name against the new frequency. The
            # receive thread resets the receiver itself (_demodulate_wfm).
            if s.get("rds") is not None:
                self._status(rds=None)
            self._pin_apply()
            self._maybe_recentre()
        if any(k in changed for k in ("seqDelayMs",)) and self.seq is not None:
            self.seq.delay = s["seqDelayMs"] / 1000.0

    def _maybe_recentre(self):
        held = self.held
        if held is not None or self.pin is not None:
            # A session holds the receiver: its centre exactly, DC on the
            # block's unused middle carrier, whatever the dial says. Or
            # background sessions pinned it: where pin_plan put it, which
            # holds them and the dial (_pin_check keeps the dial inside).
            want = held["centre"] if held is not None else self.pin
            conv = self._conv_at(want, rx=True)
            pending = self.pending_centre is not None
            if (self.pending_centre if pending else self.centre) != want or \
                    conv != (self.pending_conv if pending else self.rx_conv):
                self.pending_conv = conv
                self.pending_centre = want
            return
        rx = self._rx_dial(self.st)
        fs = self._fs()
        half = USABLE * fs / 2
        pending = self.pending_centre is not None
        c = self.pending_centre if pending else self.centre
        b = bands.band_at(rx)
        conv = self._conv_at(rx, rx=True)
        rr = self._air_range(self._ranges()[0], conv)
        planned = plan_centre(rx, b, fs, rr)
        edge = self._dial_edge(self.st)
        want = self._clear_of_dc(rx, edge, planned, half, rr)
        # A band the span holds whole has one centre whatever the dial: snap to it.
        band_based = b is not None and plan_centre(b.lo, b, fs, rr) == plan_centre(b.hi, b, fs, rr) == planned
        # Into or out of a converter's band, the device retunes whatever the centre.
        other = conv != (self.pending_conv if pending else self.rx_conv)
        if c is None or other or not (c - half + edge <= rx <= c + half - edge) or (band_based and c != want) \
                or abs(rx - c) < edge + spanfit.DC_GUARD_HZ:
            self.pending_conv = conv
            self.pending_centre = want

    @staticmethod
    def _clear_of_dc(rx: float, edge: float, centre: float, half: float, rr: tuple[float, float]) -> float:
        """`centre`, or the nearest centre to it that keeps the receive
        dial's passband clear of DC (the DC keep-out, below)."""
        if abs(rx - centre) >= edge + spanfit.DC_GUARD_HZ:
            return centre
        moved = spanfit.choose_centre([(rx, edge)], half, prefer=centre, lo=rr[0], hi=rr[1])
        return centre if moved is None else moved

    # The DC keep-out (Brian, 23/10/2026), one rule for a centre that
    # follows the dial and one pinned for decoders alike: the receiver's
    # centre - its DC, where a zero-IF radio's own spike and LO leakage
    # sit - never comes within the dial's passband plus
    # spanfit.DC_GUARD_HZ of the dial. Following the dial, a tune that
    # would land there moves the centre instead (offset tuning,
    # _maybe_recentre); pinned, the pin moves the least that clears it
    # (_pin_check); a session is fitted by the same numbers (pin_plan).
    # The DC blocker (ohscore/dsp/dcblock.py) takes the spike out; this
    # keeps what is left of it, and the LO's phase noise around it, out of
    # what the operator hears.
    @staticmethod
    def _dial_edge(s: dict) -> float:
        """How far either side of the receive dial what it hears reaches,
        by mode: the demodulator's passband (SSB's filter, CW's at its
        pitch, AM's width), FM's channel filter (its deviation plus 5 kHz,
        _configure_consumers), and wide FM's 90 kHz channel with 10 kHz to
        spare, which has to stay inside the span too, not only the dial.
        Never under 3 kHz."""
        mode = s["mode"]
        if mode == "wfm":
            return wfm.HALF_WIDTH + 10_000.0
        lo, hi = passband(mode, s["filterLo"], s["filterHi"], s["cwPitch"], s["cwWidth"], s["amWidth"])
        edge = max(abs(lo), abs(hi))
        if mode == "fm":
            edge = max(edge, float(s.get("fmDeviation", 5000.0)) + 5000.0)
        return max(3_000.0, edge)

    def _dc_block_wanted(self) -> bool:
        how = self.st.get("dcBlock", "auto")
        if how in ("on", "off"):
            return how == "on"
        return self._kind() in ZERO_IF

    # ------------------------------------------------------------ the pinned span
    # Brian, 23/10/2026 (RADIO-SDR-PLAN §8.5, "fixed sessions against a
    # moving span"): a background decoder session - APRS on 144.800, a
    # second RTTY - is on a frequency of its own, and a centre that follows
    # the dial would leave it `outside` the moment the operator tuned away.
    # So while one runs the centre is pinned: the dial moves freely inside
    # the span (the VFO channel follows it; the centre does not), and a
    # tune that would take the dial out of it is refused with the sessions
    # it would stop, unless the operator says to stop them. The other
    # choice, a second receiver for the background, needs two devices and
    # the engine has one.
    #
    # The span is the wide scope's (USABLE of fs/2 either side): what the
    # operator sees is exactly where the dial may go, and well inside the
    # bank's filter edges, where the decoders' channels lose nothing. No
    # session and not the dial ever sits within spanfit.DC_GUARD_HZ of the
    # centre (DC's spike). The centre is chosen when a session starts: the
    # one there now if everything fits; else the middle of the sessions
    # and the dial, nudged off any of them; else the session is refused
    # (`outside_span`, with the sentence). A dial tuned onto DC inside the
    # span moves the pin the least that clears it, when it can.
    #
    # Precedence: DAB and the band scan hold the whole receiver. The pinned
    # sessions win over a DAB start (refused `span_pinned` unless it says
    # to stop them) and a band scan (not while a decoder runs; a session
    # starting ends a scan); a session cannot start while DAB plays
    # (`receiver_busy`). Transmit never looks at any of this: it follows
    # the transmit dial through its own LO (_tx_key_up), never the capture.
    def _span_half(self) -> float:
        return USABLE * self._fs() / 2

    def _centre_now(self) -> float | None:
        return self.pending_centre if self.pending_centre is not None else self.centre

    def _centre_range(self, dial: float) -> tuple[float, float]:
        """Where the centre may go for a span around `dial`: the device's
        reach, through the converter `dial` is worked through."""
        return self._air_range(self._ranges()[0], self._conv_at(dial, rx=True))

    def _pin_items(self, extra: tuple = ()) -> list[tuple[float, float]]:
        return [(f.freq, f.half) for f in self.decoders.background()] + list(extra)

    def pin_plan(self, freq: float, half_width: float) -> float | None:
        if not self.PINS_SPAN or self.centre is None:
            return None
        s = self.st
        dial = (self._rx_dial(s), self._dial_edge(s))
        others = self._pin_items()
        lo, hi = self._centre_range(dial[0])
        keep = self.pin if self.pin is not None else self._centre_now()
        c = spanfit.choose_centre(others + [(freq, half_width), dial], self._span_half(), keep=keep, lo=lo, hi=hi)
        if c is not None:
            return c
        width = fmt.frequency(int(round(2 * self._span_half())), "kHz", 0)
        if not others:
            raise Refused("outside_span", _("{freq} is too far from the dial ({dial}): the receiver covers {width} "
                                            "at once, so tune nearer to it first").format(
                freq=_mhz(freq), dial=_mhz(dial[0]), width=width))
        raise Refused("outside_span", _("{freq} does not fit in the {width} the receiver covers together with the "
                                        "dial ({dial}) and {sessions}").format(
            freq=_mhz(freq), dial=_mhz(dial[0]), width=width, sessions=sessions_text(self.decoders.pinned_by())))

    def pin_to(self, centre: float) -> None:
        moved = self.pin != centre
        self.pin = float(centre)
        if moved:
            self.log.info("receiver centre pinned at %.0f Hz for %s", centre,
                          ", ".join(b["label"] for b in self.decoders.pinned_by()))
        if self.running:
            self._maybe_recentre()
        self._status(span=self.span_view())

    def span_changed(self) -> None:
        if self.pin is not None and not self.decoders.background():
            self.pin = None
            self.log.info("receiver centre unpinned: it follows the dial again")
            if self.running and self.centre is not None:
                self._maybe_recentre()
        self._status(span=self.span_view())

    def span_view(self) -> dict:
        c = self._centre_now()
        if c is None or not self.running:
            return {}
        half = self._span_half()
        by = self.decoders.pinned_by() if self.pin is not None else []
        return {"centreHz": c, "loHz": c - half, "hiHz": c + half, "pinned": self.pin is not None,
                "by": [b["id"] for b in by], "sessions": by}

    def _pin_check(self, clean: dict, drop: bool) -> None:
        t = self._pin_tls
        t.drop, t.move = False, None
        if self.pin is None or not any(k in clean for k in self.PIN_KEYS):
            return
        merged = {**self.st, **clean}
        rx, edge = self._rx_dial(merged), self._dial_edge(merged)
        c, half = self.pin, self._span_half()
        if abs(rx - c) + edge <= half:
            if abs(rx - c) < edge + spanfit.DC_GUARD_HZ:
                # Inside the span but on DC: the least move of the pin that
                # clears it and still holds every session. None can (they
                # fill the span): the dial goes there anyway, as an
                # unpinned one may, rather than refusing a frequency the
                # span shows as reachable.
                lo, hi = self._centre_range(rx)
                t.move = spanfit.choose_centre(self._pin_items(((rx, edge),)), half, prefer=c, lo=lo, hi=hi)
            return
        if drop:
            # Stopped once the change has applied (_pin_apply): a set()
            # refused for another reason stops nothing.
            t.drop = True
            return
        sessions = self.decoders.pinned_by()
        raise SpanPinned(_("Tuning to {freq} stops {sessions}: the receiver stays on {lo} to {hi} while they "
                           "run").format(freq=_mhz(rx), sessions=sessions_text(sessions), lo=_mhz(c - half),
                                         hi=_mhz(c + half)), sessions, rx)

    def _pin_apply(self) -> None:
        """After a set() that _pin_check let through: stop the sessions
        the operator agreed to stop, or move the pin off the dial."""
        t = self._pin_tls
        drop, move = getattr(t, "drop", False), getattr(t, "move", None)
        t.drop, t.move = False, None
        if drop:
            self.decoders.stop_background()
        elif move is not None and self.pin is not None and move != self.pin:
            self.pin = float(move)
            self.log.info("pinned centre moved to %.0f Hz: the dial was on it", move)
            self._status(span=self.span_view())

    # --------------------------------------------------------------- lifecycle
    def _start_consumers(self) -> None:
        g = self.geo
        self.fm_d = g.decimation_for(FM_RATE)
        self.fm_ch = None
        self.fm_cut = None
        self.fmdemod = FmDemod(g.fs / self.fm_d)
        # Wide FM's channel, when this receiver's rate can hold one: the
        # bank's smallest decimation giving at least 240 kS/s, its filter at
        # the 180 kHz channel's edges. Built once per start, like FM's.
        wd = g.decimation_for(wfm.WFM_RATE)
        if wfm.can_receive(g.fs / wd):
            self.wfm_ch = Channel(g, wd, cutoff=wfm.HALF_WIDTH)
            self.wfmdemod = wfm.make_demod(self.wfm_ch.rate, self.st["wfmDeemphasis"])
            self._wfm_dial = None
        else:
            self.wfm_ch = self.wfmdemod = None
            if self.st["mode"] == "wfm":
                self.toast(self._wfm_why(), "warn")
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

    def _held_retune(self) -> None:
        # Whoever takes or gives back the receiver retunes it: what wide FM
        # had decoded belongs to the station it was on.
        self._wfm_dial = None
        self._status(rds=None)
        if self.held is not None:
            if self._centre_before is None:
                self._centre_before = (self.centre, self.rx_conv)
        else:
            saved, self._centre_before = self._centre_before, None
            if saved is not None and saved[0] is not None and self.running:
                # Back where it was; _maybe_recentre still moves it if the
                # dial put back is not inside that span (another radio's).
                self.pending_centre, self.pending_conv = saved
        if self.running:
            self._maybe_recentre()

    def _app_tick(self, now: float) -> None:
        self.bandscan.tick()
        self._broadcast_tick(now)
        self._notch_tick(now)

    def _notch_tick(self, now: float) -> None:
        """dabNotch auto (notch.DabAuto) from the device's overload count,
        as broadcast gain reads it (_broadcast_tick: a new overload is the
        count rising), and the `notches` status. A change only asks for a
        reconfigure: the receive thread applies it (_apply_notches)."""
        have = self._notch_have
        if not have or self.rx_if is None or not self.running:
            self._notch_overloads = None
            if self.st.get("notches"):
                self._status(notches={})
            return
        ds = self.st.get("deviceStatus") or {}
        count = ds.get("overloads")
        count = int(count) if isinstance(count, (int, float)) else None
        over = count is not None and self._notch_overloads is not None and count > self._notch_overloads
        self._notch_overloads = count
        lo, hi = self._notch_span()
        if self.dab_auto.tick(now, over, lo, hi, self._dab_held()):
            self.log.info("dabNotch auto: %s", self.dab_auto.text())
            self.reconf = True
        self._status(notches=self._notch_view(lo, hi))

    def _notch_span(self) -> tuple[float, float]:
        half = self.geo.fs / 2
        return self.rx_if - half, self.rx_if + half

    def _dab_held(self) -> bool:
        h = self.held
        return h is not None and h.get("by") == "dab"

    def _notch_view(self, lo: float, hi: float) -> dict:
        """`notches` in api/state and api/status: per switch the device has,
        its setting, whether it is in, and why."""
        s, want = self.st, getattr(self.dev, "notch_want", {})
        out = {}
        if "dab_notch" in self._notch_have:
            setting = s["dabNotch"]
            if setting == "auto":
                why, text = self.dab_auto.why, self.dab_auto.text()
            else:
                why, text = "setting", _("in: set on") if setting == "on" else _("out: set off")
            out["dab_notch"] = {"setting": setting, "in": bool(want.get("dab_notch")), "why": why, "text": text}
        if "rf_notch" in self._notch_have:
            setting = s["rfNotch"]
            if setting != "auto":
                why, text = "setting", _("in: set on") if setting == "on" else _("out: set off")
            elif notch.auto_rf(lo, hi):
                why, text = "below_60mhz", _("in: tuned below 60 MHz, clear of MW and LW broadcasting")
            else:
                why, text = "band", _("out: tuned above 60 MHz or within MW or LW broadcasting")
            out["rf_notch"] = {"setting": setting, "in": bool(want.get("rf_notch")), "why": why, "text": text}
        return out

    # ------------------------------------------------------------ broadcast gain
    # A DAB session holding the receiver, or wide FM, plays with a gain of
    # its own (bcastgain.py says why and how). Decided here, ten times a
    # second, from what holds the receiver and the mode - not from hooks
    # on each way a station can end (stop, the radio stopping, a mode
    # change, a new session...), so a way added later cannot leave the
    # broadcast gain behind: whatever ended it, the next tick sees no
    # broadcast and the operator's own gain is what _rx_gain_wanted says.
    # The band scan's hold is not one: it hops across the band for a
    # moment at a time, and gives the receiver back the moment anyone
    # uses it. Nor is a background `wfm` decoder session: it shares the
    # receiver with the dial and every other session in the span.
    def _broadcast_key(self):
        h = self.held
        if h is not None:
            return ("dab", h["session"]) if h.get("by") == "dab" else None
        return ("wfm",) if self.st["mode"] == "wfm" else None

    def _broadcast_tick(self, now: float) -> None:
        s, bg = self.st, self.bgain
        key = self._broadcast_key()
        was = bg.wanted
        why = None
        if key is None:
            if bg.active():
                self.log.info("broadcast gain ends: the operator's %s %g dB again", s["rxGainMode"], s["rxGain"])
            bg.end()
        elif self.play is not None:
            why = ("playback", _("A recording is playing: its gain was fixed when it was recorded."))
        elif self._kind() == "hl2":
            why = ("no_rx_gain", _("The Hermes-Lite 2's receive gain is its LNA setting, which stays yours."))
        elif s["rxGainMode"] != "manual":
            why = ("agc", _("Receiver gain control is automatic: the radio's own AGC follows the station."))
        if why is not None:
            bg.idle(key, *why)
        elif key is not None:
            ds = s.get("deviceStatus") or {}
            count = ds.get("overloads")
            count = int(count) if isinstance(count, (int, float)) else None
            if bg.key != key or bg.wanted is None:
                bg.begin(key, now, ds.get("gainModel") or "db", ds.get("rfgrRange"), float(s["rxGain"]),
                         "overloaded" in ds or "overloads" in ds)
                self.log.info("broadcast gain for %s: %g (the operator's %g; %s model, %s)", key[0], bg.gain,
                              bg.operator, bg.ladder.model, "backs off on overload" if bg.adaptive else "fixed")
            else:
                if float(s["rxGain"]) != bg.operator:
                    bg.operator_changed(now, float(s["rxGain"]))
                # A new overload is the count rising where the device keeps
                # one (the SDRplay API reports each detection, acknowledged
                # and re-armed, so a lasting overload keeps counting). Its
                # `overloaded` flag only falls on a "corrected" event, and
                # read alone a flag left up after the gain came down would
                # walk the gain to the floor; it is the signal only for a
                # device with no count.
                if count is not None:
                    over = self._bg_overloads is not None and count > self._bg_overloads
                else:
                    over = bool(ds.get("overloaded"))
                before = bg.gain
                if bg.tick(now, over, self._broadcast_fibs(key)):
                    self.log.info("broadcast gain %g -> %g (%s)", before, bg.gain,
                                  f"FIB errors {bg.fib_bad:.1%}" if bg.fib_bad is not None else
                                  "overload" if bg.overloaded else "clear: creeping back")
            self._bg_overloads = count
        if bg.wanted != was:
            self.reconf = True
        self._status(broadcastGain=bg.view())

    def _broadcast_fibs(self, key) -> tuple | None:
        """(FIBs passed, FIBs failed) so far for the DAB session `key`
        names, or None (wide FM; a session with no counts yet). What the
        broadcast gain steers DAB by (bcastgain.py)."""
        if key[0] != "dab":
            return None
        stats = self.decoders.held_stats(key[1])
        ok, bad = stats.get("fibsOk"), stats.get("fibsBad")
        if isinstance(ok, (int, float)) and isinstance(bad, (int, float)):
            return int(ok), int(bad)
        return None

    def _rx_gain_wanted(self, s: dict) -> tuple:
        b = self.bgain.wanted
        return b if b is not None else super()._rx_gain_wanted(s)

    def _yielding_why(self, h: dict) -> str:
        return _("Radio is scanning {label} for its station list: it is yours again the moment you use it").format(
            label=h["block"])

    def _faster_rate(self, least: float) -> float | None:
        # The HL2 has its own rates, all far below a DAB block; the rest
        # that run at `sampleRate` (Pluto, LibreSDR, the simulator, SoapySDR
        # and the RTL-SDR) offer 2.4 MS/s, and the RSP runs at it already.
        if self._kind() == "hl2":
            return None
        rates = [float(r) for r in self.STATE.spec["sampleRate"]["choices"] if float(r) >= least]
        return min(rates) if rates else None

    def _start_status(self) -> dict:
        lo, hi = self.wide_span()
        self.pin = None
        return {"spanLo": lo, "spanHi": hi, "seqState": "rx", "swr": 0.0, "fwdW": 0.0,
                "span": {"centreHz": self.centre, "loHz": lo, "hiHz": hi, "pinned": False, "by": [], "sessions": []}}

    def _mode_caps(self, info: dict) -> dict:
        info = dict(info)
        if "am" in info:
            info["am"] = dict(info["am"], encode=True)
        why = self._wfm_why()
        if why and "wfm" in info:
            info["wfm"] = dict(info["wfm"], decode=False, missing=why)
        return info

    def _wfm_why(self) -> str:
        """'' if the receiver's rate can hold a wide FM channel, else the
        sentence saying why not: the catalogue's `missing` for wfm, the
        refusal of a set() to it, and the toast at a start in it. Asked of
        the open device's rate, or before it opens of the settings'."""
        fs = self._fs()
        try:
            rate = fs / Geometry(fs).decimation_for(wfm.WFM_RATE)
        except ValueError:
            rate = 0.0
        if wfm.can_receive(rate):
            return ""
        return _("Wide FM needs the receiver to run at {least:g} kS/s or more, and the {device} runs at "
                 "{rate:g} kS/s").format(least=wfm.WFM_RATE / 1000, device=self._kind(), rate=fs / 1000)

    def stop(self) -> None:
        super().stop()
        self.pin = None
        # The device is closed: it reopens with the operator's gain (the
        # configuration was never changed), so the policy starts afresh.
        self.bgain.end()
        self._bg_overloads = None
        self._status(span={}, broadcastGain={})
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
        if s.get("broadcastGain"):
            # The gain recorded beside it (openhamshack:gain) is the
            # operator's setting; this is what the device actually had.
            out["broadcastGain"] = s["broadcastGain"]
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
        self._apply_notches()

    def _apply_notches(self) -> None:
        """The RSP's front-end notches for where it is tuned now
        (ohsradio/notch.py), on the receive thread between two reads, as
        the gain and antenna are: from _configure_rx (a setting changed,
        or the radio started) and _rx_done (the centre moved). A device
        with no notch (anything but an RSP that has one) is never asked;
        one already holding what is wanted is not asked again, judged by
        its own record (notch_want), which survives its reconnects."""
        dev = self.dev
        have = dev.notches() if dev is not None else ()
        self._notch_have = have
        if not have or self.rx_if is None:
            return
        if self.st["keyed"]:
            # Every device with a notch is receive-only, so this cannot be
            # mid-over; as the antenna switch (Engine._configure_rx), the
            # rule is not left to a device's kind: try again unkeyed.
            self.reconf = True
            return
        lo, hi = self._notch_span()
        want = notch.wanted(self.st["dabNotch"], self.st["rfNotch"], lo, hi, dab_held=self._dab_held(),
                            overload_in=self.dab_auto.inn)
        # Only what changes: each switch is an Update of its own, and one
        # already where it should be needs none.
        had = getattr(dev, "notch_want", {})
        want = {k: v for k, v in want.items() if k in have and had.get(k) != v}
        if not want:
            return
        try:
            dev.set_notches(**want)
        except DeviceError as e:
            self.toast(_("Notch filter not changed: {error}").format(error=e), "warn")
            return
        self.log.info("notches at %.3f MHz (dab %s, rf %s): %s", self.rx_if / 1e6, self.st["dabNotch"],
                      self.st["rfNotch"], ", ".join(f"{k} {'in' if v else 'out'}" for k, v in want.items()))

    def _configure_consumers(self, s: dict) -> None:
        cut = s["fmDeviation"] + 5_000.0
        if self.fm_ch is None or cut != self.fm_cut:
            self.fm_ch = Channel(self.geo, self.fm_d, cutoff=min(cut, self.geo.fs / self.fm_d * 0.45))
            self.fm_cut = cut
        self.fmdemod.configure(s["fmDeviation"], s["sqlLevel"], s["ctcssRx"])
        if self.wfmdemod is not None:
            self.wfmdemod.set_deemphasis(s["wfmDeemphasis"])
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

    # ------------------------------------------------------------------ local frequencies
    @property
    def localfreq(self):
        """Local frequencies (ohsradio/localfreq.py): read from the bundled
        files on first use, never at start (a desktop that never opens the
        view never reads them), and the operator's list in the data folder."""
        lf = self.__dict__.get("_localfreq")
        if lf is None:
            from . import localfreq
            lf = self.__dict__["_localfreq"] = localfreq.LocalFrequencies(self.data_dir)
        return lf

    def local_frequencies(self, radius_km: float | None = None, category: str | None = None) -> dict:
        """GET api/local-frequencies: from the station's locator, within
        `radius_km` (default the localRadiusKm setting)."""
        r = self.st.get("localRadiusKm", 100) if radius_km is None else radius_km
        return self.localfreq.listing(self.st.get("locator", ""), r, category)

    def local_refresh(self, fetch, openaip_key: str | None = None) -> dict:
        """Refresh the downloadable sources (an administrator's action), and
        with them the DAB transmitter list: one action for every download
        the release's data can be brought up to date by."""
        key = self.st.get("openAipKey", "") if openaip_key is None else openaip_key
        summary = self.localfreq.refresh(fetch, self.st.get("locator", ""), float(self.st.get("localRadiusKm", 100)),
                                         key)
        summary["results"].append(self.dabtx.refresh(fetch))
        return summary

    # ------------------------------------------------------------------ DAB transmitters
    @property
    def dabtx(self):
        """The DAB transmitter list (ohsradio/dabtx.py), read on first use."""
        tx = self.__dict__.get("_dabtx")
        if tx is None:
            from . import dabtx
            tx = self.__dict__["_dabtx"] = dabtx.Transmitters(self.data_dir)
        return tx

    def decoder_meta(self, meta: dict) -> dict:
        """A decoder feed as clients get it (Decoders._meta): a DAB feed's
        TII codes (`tii`) named as `transmitters`, with each site's distance
        and bearing from the station's locator."""
        if "tii" not in meta:
            return meta
        return dict(meta, transmitters=self.dabtx.describe(meta, self.st.get("locator", "")))

    def _demodulate(self, X, starts, rx_dial: float):
        if self.st["mode"] == "wfm":
            return self._demodulate_wfm(X, starts, rx_dial)
        if self.st.get("rds") is not None or self._wfm_dial is not None:
            # Out of wide FM: its station's RDS goes, and coming back is a retune.
            self._wfm_dial = None
            self._status(rds=None)
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

    def _demodulate_wfm(self, X, starts, rx_dial: float):
        if self.wfmdemod is None:
            # A receiver too slow for it (refused at set(), but a saved mode
            # can meet a slower radio at start): silence, and the catalogue
            # and the start's toast say why.
            n = X.shape[0] * (self.geo.L // self.geo.decimation_for(AUDIO_RATE))
            return np.zeros(n, np.float32), -200.0
        d = self.wfmdemod
        if rx_dial != self._wfm_dial:
            # A retune (or the first block in wide FM): the pilot loop, the
            # blend and RDS start again, and the last station's RDS is never
            # shown against the new one. Every dial change counts, however
            # small: a few kHz off a station is another tuning to the PLL.
            d.reset()
            self._wfm_dial = rx_dial
            self._rds_rev = -1
            self._status(rds=None)
        self.wfm_ch.set_freq(self._off(rx_dial))
        heard, level = d(self.wfm_ch.take(X, starts), time.time())
        # Heard at 48 kHz as it was demodulated (never through the 12 kHz
        # path and back up); the engine's decoders and timing get 12 kHz.
        self.heard_hi = heard
        # No squelch in wide FM: what is heard is always open.
        self._status(sqlOpen=True)
        if self._rx_dial(self.st) == rx_dial:
            # Not for a block demodulated on a dial set() has just moved:
            # its RDS is the old station's (the next block resets).
            self._rds_publish(d.rds())
        return d.for_decoders(heard), level

    # The RDS fields published (shack_sdr wfm.Receiver.rds(), the library's
    # own names), in the order docs/SERVER-API.md lists them.
    RDS_FIELDS = ("pi", "ps", "rt", "pty", "ptyName", "ta", "tp", "ct", "af", "stereo", "ts")

    def _rds_publish(self, d: dict | None) -> None:
        """`rds` in the state when the receiver's RDS changed: published only
        on a new revision (the library raises `rev` when a field or the
        stereo flag changes), so ten blocks a second cost one comparison."""
        if d is None:
            if self.st.get("rds") is not None:
                self._status(rds=None)
            return
        rev = d.get("rev", 0)
        if rev == self._rds_rev:
            return
        self._rds_rev = rev
        self._status(rds={k: rds_text(d.get(k)) if k in ("ps", "rt") else d.get(k) for k in self.RDS_FIELDS})

    def audio_channels(self) -> int:
        if self.held is not None:
            return super().audio_channels()
        d = self.wfmdemod
        # In wide FM, 2 while the station's pilot holds the receiver's
        # stereo flag (StereoWfm): api/status audio.stereo follows it.
        return d.channels if self.st["mode"] == "wfm" and d is not None else 1

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
            self._apply_notches()
            self.settle_at = self.rx_samples + int(RETUNE_SETTLE * self.geo.fs)
            if self.dcblock is not None:
                # A zero-IF radio's DC moves with its LO: start the estimate
                # afresh rather than follow the step for 0.1 s.
                self.dcblock.reset()
            lo, hi = self.wide_span()
            self._status(spanLo=lo, spanHi=hi, span=self.span_view())

    def _rx_settled(self) -> bool:
        # Between a dial change that leaves the span and the end of the
        # block that applies the new centre, the channel is still taken
        # from the old one (where the dial may be off the edge); after it,
        # samples the radio took before it moved are still in its buffers
        # and in the analysis bank's overlap.
        return self.pending_centre is None and self.rx_samples >= self.settle_at

    def _meter_extra(self, s: dict) -> dict:
        out = {"fwd": s["fwdW"], "swr": s["swr"], "paTemp": s["paTemp"], "seq": s["seqState"],
               "sql": s["sqlOpen"], "estPep": s["estPep"]}
        if s["mode"] == "wfm" and self.held is None:
            # Ten times a second, so a stereo badge follows the pilot as it
            # comes and goes; `rds` in the state carries it too, but only
            # once a station has RDS.
            out["stereo"] = self.audio_channels() == 2
        out.update(self._smeter_fields(s))
        return out

    def _smeter_fields(self, s: dict) -> dict:
        """The calibrated S-meter fields on every meter item (docs/SERVER-API.md
        `meter`): `dbm` and `s` (e.g. "S9+12") while a calibration holds,
        else neither and `why`/`whyText` say why not. The raw `rx` dBFS field
        is unchanged - this only adds to it, so a client that ignores these
        four keys sees exactly what it always has."""
        if self.rx_level > -199:
            self._smeter_hist.append(self.rx_level)
        cal = smeter_cal.effective(s.get("sMeterCal") or "", s)
        if not cal.ok:
            return {"dbm": None, "s": None, "why": cal.why_code, "whyText": cal.why}
        dbm = self.rx_level + cal.offset
        return {"dbm": round(dbm, 1), "s": smeter_cal.s_text(dbm, smeter_cal.s9_dbm(s.get("vfo", 0.0))),
                "why": None, "whyText": ""}

    # ------------------------------------------------------------ S-meter calibration
    def smeter_table(self) -> dict:
        """Every stored calibration, keyed as `smeter_cal.cal_key` makes the
        key (device[@antenna][|band]): `GET api/smeter/calibrate`."""
        return smeter_cal.clean_cal(self.st.get("sMeterCal") or "")

    def smeter_average_dbfs(self):
        """(dBFS, spread) over the last 3 s, or None with no signal yet -
        the "current reading" behind the API's {"dbm": ...} form."""
        return smeter_cal.average_dbfs(list(self._smeter_hist))

    def smeter_calibrate(self, known_dbm: float, measured_dbfs: float | None = None) -> dict:
        """Calibrate this radio (band, antenna) so `measured_dbfs` - the
        3 s average now, unless the caller measured one of its own (the
        API's {"dbfs", "dbm"} form) - reads `known_dbm`. Returns the entry
        stored; raises ValueError with the reason it could not (AGC on,
        between bands, no reading, near clipping)."""
        if measured_dbfs is None:
            avg = self.smeter_average_dbfs()
            measured_dbfs = avg[0] if avg else None
        table = smeter_cal.calibrate(self.st.get("sMeterCal") or "", self.st, measured_dbfs, known_dbm,
                                     time.strftime("%Y-%m-%d"))
        self.set(sMeterCal=smeter_cal.format_cal(table))
        return table[smeter_cal.cal_key(self.st)]

    def smeter_forget(self) -> None:
        """Clear this radio's (band's, antenna's) calibration."""
        table = smeter_cal.forget(self.st.get("sMeterCal") or "", self.st)
        self.set(sMeterCal=smeter_cal.format_cal(table))

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
        if mode == "wfm":
            # Never transmitted (Engine._tx_blocked); this is what the
            # licence chip judges the dial in.
            return dial - wfm.HALF_WIDTH, dial + wfm.HALF_WIDTH
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


def _mhz(hz: float) -> str:
    """A frequency in a sentence: "144.8000 MHz" in the operator's locale."""
    return fmt.frequency(int(round(hz)), "MHz", 4)
