"""QO-100 NB's engine: ohscore.engine.Engine with the QO-100 parts.

The engine itself - threads, set/state, feeds, the safety supervisor, the
transmit loop, ptt/send, memories and the log - is ohscore/engine.py, shared
with OpenHamShack Radio; its docstring describes the threads and the safety rules.
What makes it a QO-100 transceiver is here, in the hooks Engine calls:

- the frequency model: the dial is a downlink; the receiver tunes
  IF = dl - LNB LO + rxCorr (the LO is the receive converter's,
  ohsnb/converters.py); the transmitter aims at the uplink
  dl - 8089.5 MHz + txCorr, with its LO kept outside the uplink passband
  (plan_tx_lo), through the Pluto's transmit converter when it has one;
- beacon lock (BeaconTracker, driving rxCorr in Auto; measuring only, in
  Hold and Manual), click-to-lock (BeaconFinder, `beacon_here`), and TX
  lock (TxMonitor, driving txCorr), and the beacon-level guard that trims
  TX gain;
- the transmit guard: inside the NB allocation, not on a beacon segment,
  the segment's modes and bandwidth, gain under the ceiling, an LO
  position that can reach the uplink;
- transmit power as the Pluto's own gain in dB (txGain, txGainCeiling);
- the QO-100 log: ADIF records as satellite contacts;
- an external transmitter (an IC-9700 into an upconverter): ohsnb/extrig.py
  tunes and follows it; here its keying drives TX lock's measurement, its
  corrections go to rigTxCorr between overs, and receive audio is muted
  while it transmits (the `_rig_*` methods);
- dish alignment (ohsnb/dishmeter.py): the middle beacon's SNR and the
  transponder's rise from the wideband stream, with the gain held fixed,
  a tone and an opt-in phone page, transmit refused while it is open
  (the `dish_*` methods).

    radio = Radio(cfg)           # does not open the device or transmit
    radio.start() / radio.stop() / radio.set(...) / radio.ptt(on) / radio.send(mode, **msg)
"""
from __future__ import annotations

import math
import statistics
import time

from ohscore.config import RECEIVE_ONLY_REFUSAL
from ohscore import countries, licences, txguard
from ohscore.converters import Converter
from ohscore.engine import Engine
from ohscore.modes import hsmodem

from ohsnb.i18n import _

from . import bandplan, config, state
from . import converters as nbconv
from .devices import REGISTRY
from .beaconrx import BeaconRx
from .beacontext import BeaconText
from .skimmer import BandSkimmer
from .overpower import OverpowerWatch
from .dishmeter import Best, DishMeter, PhoneServer, Tone, tone_hz
from .kgstvrx import KgStvRx
from .dsp.lock import BeaconFinder, BeaconTracker, TxMonitor
from .extrig import CAT_MODES, ExternalTx, check_settings, judge, mod_input_problem

# Receive DC sits in the middle beacon's guard band, 3.5 kHz below the beacon:
# no user is ever there, the beacon itself is clear of the DC notch, and the
# whole 500 kHz passband is in the flat middle of the SDR's filter at either
# sample rate. (At 1.2 MS/s the band could sit entirely to one side of DC,
# but its top would then be at 88 % of Nyquist, on the AD9361 filter's skirt.)
RX_CENTRE_DL = bandplan.BEACONS["middle"]["dl"] - 3_500.0
RECENTRE_HZ = 1_500.0        # retune the hardware when rxCorr has moved this far
WIDE_MARGIN = 25_000.0       # wide scope shows the passband +- this
TX_LO_MARGIN = 30_000.0      # TX LO this far outside the uplink passband (DJ0ABR's 30 kHz)
TX_USABLE = 0.40             # of fs: furthest the TX NCO may place a signal from the LO
RIG_KEYS = ("txRadio", "rigTxConverter", "rigIfBand", "converters")
CONVERTER_KEYS = ("converters", "rxConverter", "txConverter", "rigTxConverter")
RIG_NAME = {"civ": "IC-9700", "rigctld": "IC-9700 (rigctld)"}
# The uplink licence check could not be made (Radio._station_status):
# whole sentences, to be translated whole.
UPLINK_UNCHECKED = "Whether your licence allows a QO-100 uplink is not checked: {why}"
UPLINK_NO_CLASS = ("Whether your licence allows a QO-100 uplink is not checked until you choose your licence class "
                   "(Settings › Licence)")
# The same thing as the transmit card's standing warning (Engine.tx_warn,
# "licence"), for whoever is not reading the station panel. No lock: a
# class was never asked for before 08/10/2026, so every existing NB
# install has none, and locking their transmit on this update rather than
# warning would stop all of them (Brian, 08/10/2026 - the opposite of
# OpenHamShack Radio's guard, which does lock with no class, because HAM has
# required one since 05/10/2026 and nobody is upgrading into it unset).
NO_LICENCE_WARN = ("No licence class is set, so the uplink can't be checked against your licence. Transmitting "
                   "is not refused: choose yours in Settings › Licence.")
FEED_KINDS = ("wide", "zoom", "events", "lock", "meter", "state", "toast", "mmb", "midtext", "kgstv", "skim",
              "overpower")
CLICK_BEACONS = ("lower", "middle", "upper")    # what click-to-lock can be told a signal is
# The warning that our downlink is over the beacon (_level_warn). It comes
# on at LEVEL_WARN_DB over and goes only once the level is back under
# LEVEL_REARM_DB. Up to 0.1.9 it warned at anything over 0, so a signal
# sitting level with the beacon read "0.0 dB ABOVE" (seen on air, 07/10),
# and readings scattered about the line made a stream of toasts. Half a dB
# over is "clearly over" rather than rounding or a reading's scatter at
# the line (Brian, 08/10); the half dB between the two thresholds is what
# stops a level hovering at +0.5 from turning the warning on and off with
# every reading.
LEVEL_WARN_DB = 0.5
LEVEL_REARM_DB = 0.0

# TX lock on the IC-9700 (_rig_unkeyed). What NB measures there and may
# correct from: a CW carrier the operator keyed, or NB's own digital over
# matched against the audio it sent (TxMonitor's own-signal search; the
# band edge of anything else places it only roughly). Until 0.1.17 only the
# carrier counted, so a CAT PTT FT8 station never locked (Ray, 12/10/2026,
# landing +840 Hz off over after over). One over moves rigTxCorr by at most
# RIG_STEP_MAX_HZ - a wrong find costs one over 2 kHz off, not a jump
# across the band - and only from measurements most of which agree to
# within RIG_AGREE_HZ (another station or a fade gives the odd stray one),
# and at least RIG_AGREE_MIN of them: a short CAT line whose signal never
# came down (dish off, radio into a dummy load) still gets the odd
# "confident" find in noise, and on its own it moved rigTxCorr up to 2 kHz
# (seen in the CAT PTT tests, which put no signal through: 2 runs in 12).
RIG_MEASURED = ("carrier", "spectrum", "speckle")
RIG_STEP_MAX_HZ = 2_000.0
RIG_AGREE_HZ = 30.0
RIG_AGREE_MIN = 2
# Up to 0.1.18 an over's error was taken as relative to a radio that had
# obeyed the last correction, and added to rigTxCorr on top of it. On Ray's
# station (13/10/2026) the downlink TX lock found did not move when the
# 9700 did: it read -827, then -1760 and -1761 after +1760 had been
# applied, and rigTxCorr ran to +5441 Hz, which then went on air. So now
# each over measures the radio's own error - where the signal landed
# against where the 9700's frequency, as read during the over, puts it with
# no correction - and rigTxCorr is set to minus that, not stepped by it. A
# radio that obeys reads the same own error over after over (to its
# drift), whatever rigTxCorr is; one that read differently by more than
# RIG_VERIFY_HZ (or half the last step, for a big one) after a correction
# never saw that correction take effect, or the measurement is not of
# its signal. Either way the last step is undone and TX lock stops
# correcting until it is switched off and on: it says so rather than
# guess which of the two measurements was wrong. 150 Hz is several times
# the scatter seen over a good evening (+-20 Hz, 13/10) and well under any
# runaway step.
RIG_VERIFY_HZ = 150.0
# TX lock measures the IC-9700's downlink through the receiver, so a
# receive reference that is moving or was just changed is an error it would
# put on the transmitter. Ray's station, 13/10/2026: his LNB (not
# GPS-locked) drifted ~1.8 kHz in the 20 minutes of the pile-up, which
# beacon lock tracked, and just after it came beacon rejections, a changed
# LNB setting and corrections typed by hand. That was not shown to be what
# fooled TX lock - the found signal not moving with the radio is - but
# it is cheap to rule out. So an over corrects only when
# beacon lock was in Auto and locked on a beacon from RIG_RX_SETTLED_S
# before it keyed until it unkeyed, nobody changed the receive reference
# meanwhile, and rxCorr moved no more than RIG_RX_MOVE_HZ across it (a
# warming LNB moves a few Hz a second; a hardware re-centre or a re-lock
# moves it far more). 30 s is two FT8 cycles of a steady lock.
RIG_RX_SETTLED_S = 30.0
RIG_RX_MOVE_HZ = 50.0


def plan_tx_lo(target_ul: float, fs: float, current: float | None) -> float | None:
    """Where the TX LO should sit to put a signal on `target_ul`.

    The LO's own leakage and the DAC's DC offset make a carrier at the LO
    frequency, so it must never be inside the 2400.000-2400.500 uplink
    passband (and never inside it while idle either: the device powers it
    down unkeyed). Candidates are 30 kHz below and 30 kHz above the
    passband; the signal is placed by the NCO, at most TX_USABLE x fs from
    the LO so it stays well inside the DAC's interpolation filter. At
    1.2 MS/s the low LO (2399.970) reaches up to 2400.450 and the high one
    (2400.530) down to 2400.050, so the LO only moves for the top 40 kHz of
    the band - and keeps whatever position it has while that still works
    ("retune only when unavoidable"). At 600 kS/s the two cover 2400.000-
    2400.210 and 2400.290-2400.500; between them is refused.
    """
    below = bandplan.UL_LO - TX_LO_MARGIN
    above = bandplan.UL_HI + TX_LO_MARGIN
    reach = TX_USABLE * fs

    def ok(lo):
        return abs(target_ul - lo) <= reach

    if current is not None and current in (below, above) and ok(current):
        return current
    if ok(below):
        return below
    if ok(above):
        return above
    return None


class Radio(Engine):
    STATE = state.REG
    CONFIG = config.CONFIG
    DEVICES = REGISTRY
    FEED_KINDS = FEED_KINDS
    PRESETS = bandplan.PRESETS
    FREQ_KEY = "dl"
    LOG_TITLE = "OpenHamShack QO-100 NB log export"
    PROGRAM_ID = "OpenHamShack QO-100 NB"
    APP_ID = "shack-qo100nb"
    LOG_FREQ_FIELD = "freq_rx_hz"   # NB shows the downlink it heard
    THREAD_PREFIX = "ohsnb"
    LOGGER = "ohsnb.radio"
    DERIVE_ON = ("keyed", "txCorr", "rigTxCorr")
    # What a report from an on-air run is read for: when beacon lock and TX
    # lock came and went, and what the IC-9700 link did. Its frequency
    # moves continuously while the knob turns, so it is logged as it settles.
    DIAG_WATCH = Engine.DIAG_WATCH + ("rxLock", "beaconUsed", "rxReject", "txLockState", "rigLink", "rigError",
                                      "rigKeyed", "rigMode")
    DIAG_SLOW = ("rigFreq",)
    APP_NAME = "OpenHamShack QO-100 NB"
    APP_PACKAGE = "ohsnb"
    # What a recording is read for (ohscore/sigmf.py): when beacon lock came
    # and went and on which beacon, when the IC-9700 was transmitting into
    # the downlink, and how rxCorr moved.
    # Dish alignment's held gain too: it changes the receive gain behind
    # the AGC's back, and a recording that changes level for no reason it
    # records was what the Mac test of 17/10/2026 found (finding 11).
    REC_STATES = ("rxLock", "beaconUsed", "rigKeyed", "dishHeldDb")
    REC_TRACK = ("rxCorr",)
    # Playing someone else's recording must not leave their LNB's error in
    # the operator's config, nor anything derived from it: beacon lock's
    # rxCorr (and whether it was set by hand), and the transmit correction
    # a GPS-locked LNB predicts from it. Save-and-restore rather than "do
    # not persist": the engine writes the operator's own values in their
    # place whenever it saves during playback, so even a crash mid-playback
    # leaves the config as it was, and they are back the moment the radio
    # returns - beacon lock then starts from where the dish really was.
    PLAY_KEYS = Engine.PLAY_KEYS + ("rxCorr", "rxCorrHand", "txCorr", "txCorrTrusted")
    # A CAT over (ohsnb/extrig.py CatPtt) is judged again, and so ended, when
    # the operator switches CAT PTT off or changes its sound device.
    RECHECK_KEYED = Engine.RECHECK_KEYED + ("rigCatPtt", "rigTxAudioOut")
    # KG-STV pictures go out from the Beacon view's KG-STV page whatever the
    # rail's mode (its receiver is in the background, kgstvrx.py), judged and
    # keyed as any digital send (Engine.OVER_MODES).
    OVER_MODES = ("kgstv",)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.tx_lo = None
        self.tx_lock_good = 0
        self.ext: ExternalTx | None = None
        # The IC-9700 setup assistant has the port (ohsnb/rigsetup.py): no
        # CAT over meanwhile.
        self.rig_setup_busy = False
        # (how, err, own error, rig Hz) per measurement of the over (_rig_measure)
        self.rig_over: list[tuple[str, float, float, float | None]] = []
        # The last correction TX lock made and has not yet seen take effect:
        # (the own error it came from, rigTxCorr before it, its step).
        self.rig_unverified: tuple[float, float, float] | None = None
        # Why TX lock has stopped correcting the IC-9700 ("" while it may).
        self.rig_held = ""
        # Since when beacon lock has held a beacon with nobody changing the
        # receive reference (None: it is not); and that, with rxCorr, as
        # the over keyed (RIG_RX_SETTLED_S).
        self.rx_steady_since: float | None = None
        self.rig_rx: tuple[float | None, float] = (None, 0.0)
        self.rig_rx_t0 = 0.0
        self.rig_data = False
        # Over-beacon warning state (_level_warn): in an over sequence, and
        # its highest reading so far.
        self.level_over = False
        self.level_peak = 0.0
        # Beacon lock's instructions to the receive thread, which owns the
        # tracker: a restart from a correction (with its narrow rounds), and
        # a click-to-lock look in progress. Both under self.lock.
        self.track_req: tuple[float, int, bool] | None = None
        self.finder: BeaconFinder | None = None
        self.narrow_said = False     # the operator started the narrow search: say if it widens
        self.mmb: BeaconRx | None = None     # the multimedia beacon's receiver (beaconrx.py), while enabled
        self.midtext: BeaconText | None = None   # the middle beacon's text (beacontext.py), while enabled
        self.kgstv: KgStvRx | None = None        # KG-STV pictures at 10489.6249 (kgstvrx.py), while enabled
        self.skim: BandSkimmer | None = None      # the band skimmer (skimmer.py), while enabled
        self.opw: OverpowerWatch | None = None    # the over-power and LEILA watch (overpower.py), while enabled
        self.wide_x = None                        # this block's wideband samples, for the watch (_rx_wide)
        # The receive converter's LO (what lnbLo was) and the Pluto's
        # transmit converter, resolved once: both are restart settings, and
        # the receive thread reads the LO on every block.
        self.lnb_lo = nbconv.rx_lo(self.cfg)
        self.tx_conv = None
        # Dish alignment: open or not (under self.lock), its meter (built
        # and fed on the receive thread), the gain it holds (None: none
        # held), its best figure, tone and phone page.
        self.dish_on = False
        self.dish_meter: DishMeter | None = None
        self.dish_fixed: float | None = None
        self.dish_best = Best()
        self.dish_tone = Tone()
        self.dish_page: PhoneServer | None = None

    # ------------------------------------------------------------------ state
    def _adjust_set(self, clean: dict) -> None:
        # Lowering the ceiling takes the gain down with it, rather than
        # refusing the safer setting because the knob is above it.
        if "txGainCeiling" in clean and "txGain" not in clean and self.st["txGain"] > clean["txGainCeiling"]:
            clean["txGain"] = clean["txGainCeiling"]
        # The external transmitter's LO and band are checked when they are
        # set - in Settings - and not as a rule on every set(): a stored
        # config that no longer passes must not stop the operator tuning.
        if any(k in clean for k in RIG_KEYS):
            check_settings({**self.st, **clean})
        # So are the converters: the LNB, and the two transmit paths' own.
        if any(k in clean for k in CONVERTER_KEYS):
            nbconv.check({**self.st, **clean})
        # A transmit converter's most drive is a ceiling of its own: the
        # Pluto at this gain must not put more into it than it takes.
        if "txGain" in clean:
            merged = {**self.st, **clean}
            cap = self._gain_cap(merged)
            # (Over the ceiling itself is the registry rule's sentence.)
            if cap < merged["txGainCeiling"] and clean["txGain"] > cap + 1e-9:
                raise ValueError(_("Transmit gain cannot exceed {cap:g} dB: more would overdrive "
                                   "{converter} (Settings › Converters)").format(
                    cap=cap, converter=nbconv.tx_converter({**self.st, **clean}).title))
        # A correction that arrives through set() is the operator's (typed,
        # nudged, click-to-lock): beacon lock's own go straight to the state.
        if "rxCorr" in clean and "rxCorrHand" not in clean:
            clean["rxCorrHand"] = True

    def _after_set(self, changed: dict) -> None:
        self._beacon_mode_set(changed)
        if "dishPhone" in changed or ("dishPort" in changed and self.dish_page is not None):
            self._dish_phone(bool(self.st["dishPhone"]) and self.dish_on)
        if not self.running and any(k in changed for k in CONVERTER_KEYS):
            # Running, a new LNB waits for the restart Settings makes.
            self.lnb_lo = nbconv.rx_lo(self.cfg)
        if "txGain" in changed and self.st["keyed"] and self.dev is not None:
            self.dev.set_tx_gain(self.st["txGain"])
        if any(k in changed for k in ("txCorr",)):
            self.st["txPpm"] = self._ppm(self.st["txCorr"])
        if self.ext is not None and any(k in changed for k in ("vfo", "txVfo", "split", "xit", "xitOn")):
            self.ext.released()
        if self.ext is not None and any(k in changed for k in ("mode", "txFilterLo", "txFilterHi")):
            self._rig_guard(None)
        if self.ext is not None and any(k in changed for k in ("mode", "rigCatPtt")):
            self.ext.nb_mode(self.st["mode"])
        if any(k in changed for k in ("rxCorr", "beacon", "beaconMode", *CONVERTER_KEYS)):
            self._rx_reference_changed()
        if self.ext is not None and "txLock" in changed:
            # Off and on again is how the operator lifts a hold (_rig_hold).
            self._rig_lock_reset()
        if self.ext is not None and "rigTxCorrMaxHz" in changed:
            self._rig_corr_check()

    def _derived(self, rx_dial: float, tx_dial: float) -> dict:
        seg = bandplan.segment_at(rx_dial)
        ul = bandplan.ul(tx_dial) + self._tx_corr()
        return {"txUl": ul, "segment": seg["label"] if seg else "outside the transponder"}

    def _gain_cap(self, s: dict) -> float:
        """The most txGain may be: the ceiling, and under the Pluto's
        transmit converter's most drive when it has one."""
        cap = s["txGainCeiling"]
        c = nbconv.tx_converter(s) if s.get("txRadio", "sdr") == "sdr" else None
        if c is not None and c.max_drive_dbm is not None:
            cap = min(cap, math.floor((c.max_drive_dbm - nbconv.PLUTO_FULL_DBM) * 4) / 4)
        return cap

    def _tx_corr(self) -> float:
        """The correction of whichever transmitter is in use."""
        return self.st["rigTxCorr"] if self.cfg.get("txRadio", "sdr") != "sdr" else self.st["txCorr"]

    @staticmethod
    def _ppm(tx_corr: float) -> float:
        # txCorr = -(SDR reference error) x uplink, so the reference error is -txCorr/uplink.
        return round(-tx_corr / bandplan.ul(bandplan.BEACONS["middle"]["dl"]) * 1e6, 3)

    # ------------------------------------------------------- mode auto-tune
    def _mode_spots(self, mode: str) -> list[tuple[float, float, float]]:
        return bandplan.MODE_SPOTS.get(mode, [])

    # ----------------------------------------------------------- memories, log
    def save_memory(self, name: str, dl: float | None = None, mode: str | None = None) -> dict:
        return super().save_memory(name, dl, mode)

    def export_adif(self, path=None):
        """Write the whole log as ADIF 3 (satellite QSOs: PROP_MODE SAT,
        SAT_NAME QO-100, 13 cm up / 3 cm down) and return its path."""
        return super().export_adif(path)

    def pad_actions(self):
        """What the pad does here (ohscore/padactions.py, ohsnb/pad-actions.json):
        the power knob is the Pluto's transmit gain, 1 dB a detent, never
        past the ceiling (set() refuses that)."""
        from ohscore.padactions import PadActions
        return PadActions(self, state.MODES, ("txGain", 1.0, -89.75, 0.0))

    def _adif_fields(self, r: dict):
        """A QO-100 contact in ADIF: 13 cm up, 3 cm down, uplink and downlink
        frequencies, via satellite QO-100."""
        return ([("BAND", "13cm"), ("BAND_RX", "3cm"), ("FREQ", f"{bandplan.ul(r['dl']) / 1e6:.6f}"),
                 ("FREQ_RX", f"{r['dl'] / 1e6:.6f}")],
                [("PROP_MODE", "SAT"), ("SAT_NAME", "QO-100")])

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self.running:
            return
        self.lnb_lo = nbconv.rx_lo(self.cfg)
        super().start()
        # A recording has no transmitter, and the IC-9700's link would only
        # tune a real radio to follow a dial that is playing the past.
        if self.cfg["txRadio"] != "sdr" and self.play is None:
            self._rig_lock_reset()
            self._rig_corr_check()
            # TX lock watches for the external radio's signal, not ours; the
            # baseline is learnt the same way, while it is not transmitting.
            self.monitor.trusted = self.st["rigTxCorrTrusted"]
            self.monitor.set_external(*self._rig_template())
            self.ext = ExternalTx(self)
            self.ext.start()

    def stop(self) -> None:
        if self.ext is not None:
            # A CAT over ends first, while the link still holds the port to
            # unkey through (Engine.stop would end it only after the link
            # had gone, and the radio would stay on the air).
            self._unkey("", None, "radio stopped")
            if self.tx_thread:
                self.tx_thread.join(timeout=3)
            self.ext.stop()
            self.ext = None
        super().stop()
        self._mmb_enable(False)
        self._midtext_enable(False)
        self._kgstv_enable(False)
        self._skim_enable(False)
        self._opw_enable(False)

    def test_rig(self, changes: dict | None = None) -> str:
        """Settings' "Test connection": read the external radio's frequency
        once, with the settings as the dialog has them (`changes` over the
        current ones), and say what came back. Reads only. Raises
        ohscore.rig.RigError (a sentence) when it does not answer."""
        from ohscore.rig import RigError, probe
        cfg = {**self.cfg, **(changes or {})}
        kind = cfg.get("txRadio", "sdr")
        if kind == "sdr":
            raise RigError("Choose IC-9700 (CI-V) or Hamlib rigctld first")
        link_keys = ("txRadio", "civPort", "civBaud", "civAddress", "rigctldHost", "rigctldPort")
        if self.ext is not None and all(cfg.get(k) == self.cfg.get(k) for k in link_keys):
            # The link already holds the port (Windows refuses a second open).
            f = self.ext.link.read_now()
        else:
            f = probe(kind, cfg)
        return f"{RIG_NAME[kind]} answered: {f / 1e6:.6f} MHz"

    def _start_consumers(self) -> None:
        # A stored correction is where the beacon was last time: looked at
        # narrowly first, as after losing it (BeaconTracker.TIGHT_HZ).
        corr = self.st["rxCorr"]
        self.tracker = BeaconTracker(self.geo, self.st["beacon"], self.st["beaconSearchHz"], corr,
                                     narrow=BeaconTracker.NARROW_START if corr else 0)
        with self.lock:
            self.track_req, self.finder = None, None
        self.monitor = TxMonitor(self.geo, self.st["rttSec"], trusted=self.st["txCorrTrusted"])
        self.mon_ch = self.monitor.ch
        # A (re)started radio has opened with its configured gain: dish
        # alignment, if open, builds its meter and holds the gain afresh.
        self.dish_meter = None

    def _initial_tuning(self) -> float:
        self.tuned_corr = self.st["rxCorr"]
        return RX_CENTRE_DL - self.lnb_lo + self.st["rxCorr"]

    def _start_status(self) -> dict:
        auto = self.st["beaconMode"] == "auto"
        return {"rxLock": "searching" if auto else self.st["beaconMode"], "txLockState": "idle",
                "rxWindow": float(self.tracker.TIGHT_HZ if self.tracker.narrow_left else self.st["beaconSearchHz"])
                if auto else 0.0, "txPpm": self._ppm(self.st["txCorr"])}

    def _save_extra(self, cfg: dict) -> None:
        cfg["rxCorr"], cfg["txCorr"] = self.st["rxCorr"], self.st["txCorr"]
        cfg["txCorrTrusted"] = self.st["txCorrTrusted"]
        cfg["rxCorrHand"] = self.st["rxCorrHand"]
        cfg["rigTxCorr"], cfg["rigTxCorrTrusted"] = self.st["rigTxCorr"], self.st["rigTxCorrTrusted"]

    def _supervise_status(self) -> dict:
        return {"txCorr": self.st["txCorr"]}

    # ------------------------------------------------------------- diagnostics
    def _diag_detail(self, key: str, s: dict) -> str:
        if key in ("rxLock", "beaconUsed"):
            return (f" (rxCorr {s['rxCorr']:+.1f} Hz{' by hand' if s['rxCorrHand'] else ''}, err {s['rxErr']:+.1f} Hz, "
                    f"snr {s['rxSnr']:.1f} dB, beacon {s['beaconUsed'] or '-'}, mode {s['beaconMode']})")
        if key == "rxReject":
            return f" (rxCorr {s['rxCorr']:+.1f} Hz, search +-{s['rxWindow'] / 1000:g} kHz)"
        if key == "txLockState":
            ext = self.cfg.get("txRadio", "sdr") != "sdr"
            corr = s["rigTxCorr"] if ext else s["txCorr"]
            return f" ({'rigTxCorr' if ext else 'txCorr'} {corr:+.1f} Hz, txPpm {s['txPpm']:+.3f})"
        if key in ("rigLink", "rigKeyed"):
            f = s.get("rigFreq")
            return f" (rig {f / 1e6:.6f} MHz)" if f else ""
        return super()._diag_detail(key, s)

    def _diag_extra(self, s: dict) -> str:
        vs = s.get("vsBeacon")
        out = (f"rx-lock {s['rxLock']} corr {s['rxCorr']:+.1f} err {s['rxErr']:+.1f} snr {s['rxSnr']:.1f} "
               f"[{s['beaconUsed'] or '-'}] tx-lock {s['txLockState']} txCorr {s['txCorr']:+.1f}"
               + ("" if vs is None else f" vsBeacon {vs:+.1f} dB"))
        if self.cfg.get("txRadio", "sdr") != "sdr":
            f = s.get("rigFreq")
            out += (f" | rig {s['rigLink']} {f / 1e6 if f else 0:.6f} MHz {s.get('rigMode') or '-'}"
                    f"{' TX' if s.get('rigKeyed') else ''} rigTxCorr {s['rigTxCorr']:+.1f}")
        return out

    # ------------------------------------------------------------- frequencies
    def _off(self, dl: float) -> float:
        """Offset from the IQ stream's DC of a downlink frequency, given the
        current receive correction: IF = dl - LNB LO + rxCorr."""
        return dl - self.lnb_lo + self.st["rxCorr"] - self.rx_if

    def _dial_at(self, off: float) -> float:
        # Offset from DC, plus rx_if and the LNB's LO, minus rxCorr to undo
        # the error: beacons come out on their nominal frequencies.
        return off + self.rx_if + self.lnb_lo - self.st["rxCorr"]

    def wide_span(self) -> tuple[float, float]:
        # The passband +- WIDE_MARGIN.
        return bandplan.DL_LO - WIDE_MARGIN, bandplan.DL_HI + WIDE_MARGIN

    # ---------------------------------------------------------------- recording
    def _rec_centre(self) -> tuple[float, float]:
        # The downlink the hardware is tuned to through the LNB as it is
        # nominally - not the corrected dial, which moves with every rxCorr
        # update; the true downlink at DC is this minus rxCorr, and rxCorr
        # is in the metadata (at the start, and tracked).
        return float(self.rx_if), float(self.rx_if + self.lnb_lo)

    def _rec_extra(self, s: dict) -> dict:
        conv = nbconv.rx_converter(self.cfg)
        return {"converter": conv.to_dict() if conv is not None else None,
                "beacon_lock": {k: s.get(k) for k in ("rxCorr", "rxCorrHand", "rxLock", "beaconMode", "beacon",
                                                     "beaconUsed", "rxErr", "rxSnr", "beaconLevel", "rxWindow",
                                                     "beaconSearchHz", "lnbGpsLocked")},
                "frequency_model": "IF = downlink - converter rxOffset + rxCorr; core:frequency is the downlink "
                                   "at DC before rxCorr, so the true downlink there is core:frequency - rxCorr"}

    # ---------------------------------------------------------------- playback
    def _play_converter(self):
        # The LNB as this station has it: a recording's core:frequency is
        # the nominal downlink at DC, so it plays on the right frequencies
        # whatever LO the recorder's LNB had.
        return Converter("LNB", rx_offset=self.lnb_lo)

    def _play_seed(self, meta: dict) -> dict:
        # The recording's own rxCorr seeds beacon lock, which then starts
        # with its narrow search round it (as from a stored correction) and
        # widens if the beacon is not there. Ours keep it with the beacon
        # lock state; the hand-made recordings of 07/10/2026 as lnb_error_hz.
        g = meta["global"]
        out = super()._play_seed(meta)
        corr = (g.get("openhamshack:beacon_lock") or {}).get("rxCorr")
        if corr is None:
            corr = g.get("openhamshack:lnb_error_hz")
        if isinstance(corr, (int, float)):
            out.update(rxCorr=float(corr), rxCorrHand=False)
        return out

    # ------------------------------------------------------------------ receive
    def _configure_consumers(self, s: dict) -> None:
        self.tracker.choice = s["beacon"]
        self.tracker.search_hz = s["beaconSearchHz"]
        self.monitor.rtt = s["rttSec"]
        self._mmb_enable(bool(s["mmbDecode"]) and self.running)
        self._midtext_enable(bool(s["midTextDecode"]) and self.running)
        self._kgstv_enable(bool(s["kgstvDecode"]) and self.running)
        self._skim_enable(bool(s["skimDecode"]) and self.running)
        self._opw_enable(bool(s["opWatch"]) and self.running)
        sk = self.skim
        if sk is not None:
            sk.set_budget(s["skimBudget"])

    # ------------------------------------------------------- multimedia beacon
    def _mmb_enable(self, on: bool) -> None:
        """Start or stop the multimedia beacon's receiver (beaconrx.py). Runs
        on the receive thread (or after it has stopped), the only thread
        that feeds it."""
        if on and self.mmb is None:
            if not hsmodem.AVAILABLE:
                self._status(mmbState=f"unavailable: {hsmodem.WHY_NOT}")
                return
            self.mmb = BeaconRx(self)
            self.mmb.start()
        elif not on and self.mmb is not None:
            self.mmb.stop()
            self.mmb = None

    # ------------------------------------------------------ middle beacon text
    def _midtext_enable(self, on: bool) -> None:
        """Start or stop the middle beacon's text receiver (beacontext.py),
        as _mmb_enable does the multimedia beacon's."""
        if on and self.midtext is None:
            self.midtext = BeaconText(self)
            self.midtext.start()
        elif not on and self.midtext is not None:
            self.midtext.stop()
            self.midtext = None

    # ------------------------------------------------------------ KG-STV
    def _kgstv_enable(self, on: bool) -> None:
        """Start or stop the KG-STV picture receiver (kgstvrx.py), as
        _mmb_enable does the multimedia beacon's."""
        if on and self.kgstv is None:
            self.kgstv = KgStvRx(self)
            self.kgstv.start()
        elif not on and self.kgstv is not None:
            self.kgstv.stop()
            self.kgstv = None

    # ------------------------------------------------------------ band skimmer
    def _skim_enable(self, on: bool) -> None:
        """Start or stop the band skimmer (skimmer.py), as _mmb_enable does
        the multimedia beacon's receiver."""
        if on and self.skim is None:
            self.skim = BandSkimmer(self)
            self.skim.start()
        elif not on and self.skim is not None:
            self.skim.stop()
            self.skim = None

    # ------------------------------------------------- over-power and LEILA
    def _opw_enable(self, on: bool) -> None:
        """Start or stop the over-power and LEILA watch (overpower.py), as
        _mmb_enable does the multimedia beacon's receiver."""
        if on and self.opw is None:
            self.opw = OverpowerWatch(self)
            self.opw.start()
        elif not on and self.opw is not None:
            self.opw.stop()
            self.opw = None

    def overpower_view(self) -> dict:
        """The watch's list and state (docs/ENGINE-API.md `overpower`): what
        the server's GET api/overpower answers."""
        w = self.opw
        if w is None:
            return {"state": "off", "beacon": "", "marginDb": None, "capture": bool(self.st["leilaCapture"]),
                    "lastCapture": self.st["opCapture"], "events": []}
        return w.view()

    def leila_capture_now(self) -> None:
        """Save the LEILA evidence ring now (the operator heard a siren and
        nothing fired). Raises ValueError with a sentence when there is
        nothing to save. Receive only."""
        w = self.opw
        if w is None:
            raise ValueError(_("The over-power watch is off (Settings › LNB & locks)"))
        w.capture_now()

    def _emit_event(self, ev: dict):
        super()._emit_event(ev)
        # The calls heard in a calling window go on the skimmer's entry for
        # it. Not by subscribing to "events": a feed drained counts as the
        # UI being alive to the transmit watchdog (Engine._supervise).
        sk = self.skim
        if sk is not None:
            sk.heard(ev)
        w = self.opw
        if w is not None:
            w.heard(ev)

    # ------------------------------------------------------------ beacon lock
    # Auto: the tracker searches and tracks, and moves rxCorr. Hold and
    # Manual: it only measures (the beacon's level for the level guard,
    # its error for the operator), and rxCorr moves only when the operator
    # moves it. Either way the receive thread is the only one that touches
    # the tracker; set() and click-to-lock leave it instructions.
    def _beacon_mode_set(self, changed: dict) -> None:
        if not ("rxCorr" in changed or "beaconMode" in changed):
            return
        mode = self.st["beaconMode"]
        status = {}
        with self.lock:
            if mode == "auto":
                if "beaconMode" in changed:
                    # Back to Auto: from the correction held, narrowly first.
                    self.track_req = (self.st["rxCorr"], BeaconTracker.NARROW_START, False)
                else:
                    # The operator said where the beacon is: believed for longer.
                    self.track_req = (self.st["rxCorr"], BeaconTracker.NARROW_HAND, True)
                self.narrow_said = True
                status = {"rxLock": "searching", "rxWindow": BeaconTracker.TIGHT_HZ}
            elif "beaconMode" in changed:
                self.track_req = None
                status = {"rxLock": mode, "rxRate": 0.0, "rxWindow": 0.0}
        if status and self.running:
            self._status(**status)

    def beacon_here(self, beacon: str, dl: float, snap: bool = True) -> None:
        """Click-to-lock: the signal at downlink `dl`, as the scopes show it
        now, is the `beacon` ("lower", "middle" or "upper"). rxCorr is set so
        that it lands on that beacon's reference - after a second's look for
        the beacon's exact centre within BeaconFinder.SNAP_HZ of `dl`, when
        `snap` and the radio is running; else at once, from `dl` itself,
        which then counts as the beacon's marked frequency on the scope.
        In Auto the tracker then searches only +-2 kHz around it, so it
        locks to the operator's choice, not to whatever is strongest in the
        whole range. A toast says what happened. Never keys anything."""
        if beacon not in CLICK_BEACONS:
            raise ValueError(_("beacon must be one of {names}").format(names=", ".join(CLICK_BEACONS)))
        apparent = float(dl) - self.lnb_lo + self.st["rxCorr"]
        if not (self.running and snap):
            self._pinned(beacon, apparent, None)
            return
        with self.lock:
            self.finder = BeaconFinder(self.geo, beacon, apparent)

    def _pinned(self, beacon: str, apparent: float, res: dict | None) -> None:
        """Click-to-lock's result: the hand-set correction, and its toast."""
        info = bandplan.BEACONS[beacon]
        lnb = self.lnb_lo
        if res and res["found"]:
            corr = apparent + res["offset"] - (info["ref"] - lnb)
            how = _("snapped {offset:+.0f} Hz to {why}").format(offset=res["offset"], why=res["why"])
        else:
            # Nothing clear to snap to: the click itself is the beacon, at the
            # frequency its marker stands on (an F1A beacon's is its nominal
            # tone, not the midpoint of the pair).
            mark = info["dl"] if info["kind"] == "f1a" else info["ref"]
            corr = apparent - (mark - lnb)
            how = (_("{why}, so the click itself was used").format(why=res["why"]) if res else
                   _("set from the click"))
        title = info["name"].split(" (")[0]
        try:
            self.set(rxCorr=round(corr, 1))
        except ValueError as e:
            self.toast(_("Not locked to the {beacon} there: {error}").format(beacon=title.lower(), error=e), "warn")
            return
        mode = self.st["beaconMode"]
        # One whole sentence per beacon mode rather than a translated tail
        # joined on: other languages may not put the mode's clause last.
        # `how` is a parenthetical that stands alone in any language.
        if mode == "auto":
            said = _("{title} set where you clicked ({how}): rxCorr {corr:+.0f} Hz; "
                     "beacon lock is searching +-{span:g} kHz there")
        elif mode == "hold":
            said = _("{title} set where you clicked ({how}): rxCorr {corr:+.0f} Hz; "
                     "beacon lock is on Hold, so nothing follows the drift")
        else:
            said = _("{title} set where you clicked ({how}): rxCorr {corr:+.0f} Hz; "
                     "beacon lock is on Manual, so nothing follows the drift")
        self.toast(said.format(title=title, how=how, corr=corr, span=BeaconTracker.TIGHT_HZ / 1000), "info")

    def _rx_track(self, X, starts, t_stream: float) -> None:
        with self.lock:
            req, self.track_req = self.track_req, None
            fin = self.finder
        if req is not None:
            self.tracker.reset(req[0], narrow=req[1], trusted=req[2])
        if fin is not None:
            # Nothing tracks while the operator's click is being looked at:
            # its result replaces whatever the tracker would conclude.
            res = fin.feed(X, starts, self.rx_if)
            if res is not None:
                with self.lock:
                    if self.finder is fin:
                        self.finder = None
                self._pinned(fin.name, fin.apparent, res)
            return
        lnb = self.lnb_lo
        if self.st["beaconMode"] == "auto":
            rep = self.tracker.process(X, starts, self.rx_if, lnb, t_stream)
            if rep:
                self._on_rx_lock(rep)
        else:
            rep = self.tracker.measure(X, starts, self.rx_if, lnb, t_stream, self.st["rxCorr"])
            if rep:
                self._on_rx_held(rep)

    def _on_rx_held(self, rep: dict) -> None:
        self._status(rxErr=float(rep.get("err", 0.0) or 0.0), rxRate=0.0, rxSnr=float(rep.get("snr", 0.0) or 0.0),
                     beaconUsed=rep.get("used", "") or "", beaconLevel=float(self.tracker.level_db),
                     rxReject=self.tracker.why)
        self._publish("lock", {"t": time.time(), "kind": "rx", **rep})

    def _rx_monitor(self, X, starts, t_stream: float) -> None:
        mmb = self.mmb       # read once: stop() may clear it from another thread
        if mmb is not None:
            mmb.feed(X, starts)
        # The middle beacon's text: its channel sits where beacon lock has
        # just put the beacon (rxCorr), so the decoder only follows the rest.
        mt = self.midtext
        if mt is not None:
            mt.feed(X, starts)
        kg = self.kgstv
        if kg is not None:
            kg.feed(X, starts)
        # The band skimmer: only the spectra, by reference; its thread does the rest.
        sk = self.skim
        if sk is not None:
            sk.feed(X, starts)
        w, x = self.opw, self.wide_x
        if w is not None and x is not None:
            w.feed(x, X, starts)
        self.wide_x = None
        # TX monitor channel: always running, so the baseline is learnt unkeyed.
        s = self.st
        txd = (s["txVfo"] if s["split"] else s["vfo"]) + (s["xit"] if s["xitOn"] else 0.0)
        mf = self._off(txd)
        if abs(mf - self.mon_ch.freq) > 1.0:
            if abs(mf - self.mon_ch.freq) > 50.0:
                self.monitor.retuned(t_stream)
            self.mon_ch.set_freq(mf)
        my = self.mon_ch.take(X, starts)
        res = self.monitor.rx(my, t_stream)
        if res:
            self._on_tx_measure(res, t_stream)

    def _meter_extra(self, s: dict) -> dict:
        return {"vsBeacon": s["vsBeacon"], "beacon": round(s["beaconLevel"], 1), "rigKeyed": s["rigKeyed"]}

    def _rx_audio_gain(self, s: dict) -> float:
        return self.ext.audio_gain(s) if self.ext is not None else 1.0

    def _rx_done(self, s: dict) -> None:
        # Re-centre the hardware when the LNB has wandered far enough that DC
        # would leave the beacon guard. The channels follow exactly, because
        # every offset is computed from rx_if.
        if abs(s["rxCorr"] - self.tuned_corr) > RECENTRE_HZ:
            self.rx_if = RX_CENTRE_DL - self.lnb_lo + s["rxCorr"]
            self.tuned_corr = s["rxCorr"]
            self.dev.set_rx_if(self.rx_if)

    def _on_rx_lock(self, rep: dict):
        state_ = rep["state"]
        corr = float(rep["rxCorr"])
        with self.lock:
            # A report the operator has overtaken (a new correction, a mode
            # change, a click being looked at) must not overwrite them.
            if self.track_req is not None or self.finder is not None or self.st["beaconMode"] != "auto":
                return
            self.st["rxCorr"] = corr
            self.dirty_locks = True
            # Found by a full-width search: the beacon's own word, whoever
            # set the correction before.
            if rep.get("acquired") is not None and rep.get("wide") and self.st["rxCorrHand"]:
                self.st["rxCorrHand"] = False
                self.pending["rxCorrHand"] = False
        extra = {"rxWindow": float(rep["window"])} if "window" in rep else {}
        if state_ == "locked":
            extra["rxWindow"] = 0.0
        self._status(rxLock=state_, rxErr=float(rep.get("err", 0.0) or 0.0), rxRate=float(rep.get("rate", 0.0) or 0.0),
                     rxSnr=float(rep.get("snr", 0.0) or 0.0), beaconUsed=rep.get("used", "") or "",
                     beaconLevel=float(self.tracker.level_db), rxReject=self.tracker.why, **extra)
        self.pending["rxCorr"] = corr
        if state_ == "locked" and rep.get("used"):
            if self.rx_steady_since is None:
                self.rx_steady_since = time.monotonic()
        else:
            self.rx_steady_since = None
        self._publish("lock", {"t": time.time(), "kind": "rx", **rep})
        if rep.get("widened") and self.narrow_said:
            self.toast(_("Beacon lock: no beacon within +-{tight:g} kHz of the correction "
                         "held; searching +-{search:g} kHz").format(
                tight=BeaconTracker.TIGHT_HZ / 1000, search=self.st["beaconSearchHz"] / 1000), "info")
        if state_ == "locked" or rep.get("widened"):
            self.narrow_said = False
        # GPS-locked LNB: the beacon error is (almost) all the SDR's reference.
        # An SDR whose reference is off by p (fractional) tunes every frequency
        # f to f(1+p): the receiver, set to the IF f_rx, makes everything appear
        # p*f_rx LOW, so rxCorr = -p*f_rx; our uplink u goes out at u(1+p),
        # p*u HIGH, so it needs txCorr = -p*u = rxCorr * u / f_rx. The IF is
        # ~740 MHz and the uplink 2400 MHz, so txCorr ~ 3.2 x rxCorr.
        # Only from a correction beacon lock found itself: one the operator
        # set (rxCorrHand) may be on the wrong signal, and 3.2 x its error
        # would send the first over that far off.
        if (state_ == "locked" and self.st["lnbGpsLocked"] and not self.st["txCorrTrusted"]
                and not self.st["rxCorrHand"] and not self.st["keyed"] and self.ext is None):
            u = bandplan.ul(self.st["txDial"])
            f_rx = self.rx_if + (self.st["rxDial"] - RX_CENTRE_DL)
            pred = corr * u / f_rx
            with self.lock:
                self.st["txCorr"] = pred
                self.st["txCorrTrusted"] = True
                self.dirty_locks = True
            self.monitor.trusted = True
            self._status(txPpm=self._ppm(pred))
            self.pending["txCorr"] = pred
            self.toast(_("GPS-locked LNB: predicted transmit correction {pred:+.0f} Hz").format(pred=pred), "info")

    def _on_tx_measure(self, res: dict, t_stream: float):
        s = self.st
        out = {"t": time.time(), "kind": "tx", "err": round(res["err"], 1), "z": round(res["z"], 1), "how": res.get("how"), "delay": res.get("delay"),
               "confident": res["confident"], "window": res["window"]}
        if res.get("widened"):
            self.toast(_("Own signal not found near the expected place; searching the whole band"), "info")
        rig = self.ext is not None
        if not (s["rigKeyed"] if rig else s["keyed"]):
            return
        self.own_tries = getattr(self, "own_tries", 0) + 1
        if res["confident"]:
            err = res["err"]
            with self.lock:
                own_dl = s["txDial"] + err
            vs = None
            if self.tracker.level_lin > 0 and res["own"] > 0:
                vs = 10 * math.log10(res["own"] / self.tracker.level_lin)
            self._status(txErr=float(err), txConfidence=float(res["z"]), ownDl=float(own_dl),
                         vsBeacon=None if vs is None else round(vs, 1))
            if hasattr(self, "own_over"):
                self.own_over.append((vs, float(err), res.get("how")))
            out.update(ownDl=own_dl, vsBeacon=None if vs is None else round(vs, 1))
            if rig:
                self._rig_measure(res, out, vs)
            elif s["txLock"]:
                wide = not self.monitor.trusted
                step = err if wide else 0.7 * err
                with self.lock:
                    s["txCorr"] = s["txCorr"] - step
                    if wide:
                        s["txCorrTrusted"] = True
                    self.dirty_locks = True
                self.monitor.trusted = True
                self.monitor.corrected(t_stream, self.dev.tx_latency())
                self.tx_lock_good = self.tx_lock_good + 1 if abs(err) < 25 else 0
                self.pending["txCorr"] = s["txCorr"]
                # Found but off the dial is "landed", not "searching": the
                # signal is found and txCorr already moved by the error
                # (the status strip shows it), and the next measurement
                # confirms. Until 0.1.5 this said searching, so the badge
                # read "SEARCHING -2.900 kHz" beside a txCorr of +2900 Hz -
                # as if still lost and still 2.9 kHz out.
                self._status(txLockState="locked" if self.tx_lock_good >= 1 and abs(err) < 25 else "landed",
                             txPpm=self._ppm(s["txCorr"]), txUl=bandplan.ul(s["txDial"]) + s["txCorr"])
                out.update(txCorr=s["txCorr"], applied=-step)
            if vs is not None:
                self._level_warn(vs, rig)
            if vs is not None and not rig:
                self._level_guard(vs)
        else:
            self._status(txConfidence=float(res["z"]))
        self._publish("lock", out)

    def _level_warn(self, vs: float, rig: bool) -> None:
        """Licence: our downlink no stronger than the beacon (LEILA enforces
        it). The standing warning, from Pluto or IC-9700 alike: on once the
        level is clearly over (LEVEL_WARN_DB), its figure kept current
        while the over sequence lasts, off once the level is back under
        LEVEL_REARM_DB. Logged once per sequence, not per reading."""
        if not self.level_over:
            if vs < LEVEL_WARN_DB:
                return
            self.level_over = True
            self.level_peak = vs
        elif vs < LEVEL_REARM_DB:
            self.level_over = False
            self.tx_clear("level")
            return
        self.level_peak = max(self.level_peak, vs)
        self.tx_warn("level", f"Your downlink is {vs:.1f} dB above the beacon - reduce power"
                              + (" on the IC-9700" if rig else ""), "warn")

    def _level_after_over(self) -> None:
        """The over ended while still over the beacon: the warning stays
        until the next over, in the past tense, so a short over's warning
        is not gone the moment PTT is released."""
        self._log_own_signal()
        if self.level_over:
            self.level_over = False
            self.tx_warn("level", f"Your last over reached {self.level_peak:.1f} dB above the beacon - reduce "
                                  "power before the next", "warn")

    def _level_new_over(self) -> None:
        """A new over: the last over's level and trim notes no longer apply."""
        self.level_over = False
        self.level_peak = 0.0
        self.own_over = []
        self.own_tries = 0
        self.tx_clear("level", "trim")

    def _log_own_signal(self) -> None:
        """The over's own-signal result as one line: how often TX lock
        found the downlink, how strong it was against the beacon and how
        far off frequency. With the over-start and over-end lines it says
        whether an over that went out also came back down - the question
        Ray's log could not answer."""
        found, tries = getattr(self, "own_over", []), getattr(self, "own_tries", 0)
        self.own_over, self.own_tries = [], 0
        if not tries:
            return
        if not found:
            self.log.info("own signal: not found in %d measurements", tries)
            return
        vs = sorted(v for v, _e, _h in found if v is not None)
        errs = sorted(e for _v, e, _h in found)
        level = (f"vs beacon max {vs[-1]:+.1f} dB, median {vs[len(vs) // 2]:+.1f} dB" if vs
                 else "no beacon level to compare")
        self.log.info("own signal: found in %d of %d measurements, %s, frequency error median %+.0f Hz (%s)",
                      len(found), tries, level, errs[len(errs) // 2],
                      ", ".join(sorted({h or "?" for _v, _e, h in found})))

    def _level_guard(self, vs: float):
        """The level guard's action on our own transmitter (levelMode).
        Its threshold is the operator's margin under the beacon plus half a
        dB, not the beacon itself, so the over-beacon warning's 0.0 dB
        mistake (LEVEL_WARN_DB) never applied to it; it is unchanged."""
        s = self.st
        target = -s["levelMarginDb"]
        mode = s["levelMode"]
        if mode in ("limit", "auto") and vs > target + 0.5:
            new = max(-89.75, s["txGain"] - (vs - target))
            self._set_gain_internal(new, f"Transmit gain trimmed to {new:.1f} dB to stay {s['levelMarginDb']:g} dB under the beacon")
        elif mode == "auto" and vs < target - 1.0:
            new = min(self._gain_cap(s), s["txGain"] + min(1.0, target - vs))
            if new > s["txGain"] + 0.05:
                self._set_gain_internal(new, None)

    def _set_gain_internal(self, db: float, note: str | None):
        db = round(max(-89.75, min(self._gain_cap(self.st), db)) * 4) / 4   # Pluto: 0.25 dB steps
        with self.lock:
            if db == self.st["txGain"]:
                return
            self.st["txGain"] = db
            self.cfg["txGain"] = db
            self.dirty = True
            self.pending["txGain"] = db
        if self.dev is not None and self.st["keyed"]:
            self.dev.set_tx_gain(db)
        if note:
            # Standing, not a toast: in Limit it fires on each trim of an
            # over, and the newest is the one that matters.
            self.tx_warn("trim", note, "info")

    # ------------------------------------------------- the external transmitter
    def _rig_template(self) -> tuple[str, float, float]:
        """What TX lock looks for while the external radio transmits, by
        its mode on air: a carrier at the dial in CW (Icom transmits CW on
        the displayed frequency), else the audio passband beside it."""
        s = self.st
        m = s.get("rigMode") or ""
        if m in ("cw", "cw-r"):
            return "carrier", 0.0, 0.0
        lo, hi = s["txFilterLo"], s["txFilterHi"]
        if m in ("lsb", "rtty-r"):
            return "band", -hi, -lo
        return "band", lo, hi

    def _rig_keyed(self) -> None:
        """The external radio went to transmit (its link thread saw it).
        An over NB keyed by CAT carries audio NB rendered and has handed
        to the monitor block by block (_tx_sent), so TX lock matches that,
        exactly as it matches the Pluto's baseband: FT8's tones, a PSK
        line, a CW line's tone - wherever in the passband they were put.
        Anything else the radio sends (the operator's own PTT) is unknown
        to NB, and only its template can be looked for."""
        if self._cat_now():
            self.monitor.set_external(None)
        else:
            self.monitor.set_external(*self._rig_template())
        self.monitor.set_keyed(True, self.rx_samples / self.geo.fs)
        self.rig_over = []
        self.rig_rx = (self.rx_steady_since, self.st["rxCorr"])
        self.rig_rx_t0 = time.monotonic()
        self._level_new_over()
        self._status(rigKeyed=True, txLockState="searching", vsBeacon=None)

    def _rig_unkeyed(self, apply: bool) -> None:
        """It went back to receive (or the link was lost: apply=False).
        The over's exact measurements (RIG_MEASURED) become one correction,
        which the link sends to the radio as soon as it is back on receive
        - see ohsnb/extrig.py for why never during the over. What is
        corrected is the radio's own error, measured against the frequency
        it was on (RIG_VERIFY_HZ says why, and what happens when it does
        not hold still)."""
        self.monitor.set_keyed(False, self.rx_samples / self.geo.fs)
        over = [m for m in self.rig_over if m[0] in RIG_MEASURED]
        self.rig_over = []
        self._level_after_over()
        self._status(rigKeyed=False, txLockState="idle")
        if not (apply and over and self.st["txLock"]):
            return
        if len({f for _h, _e, _o, f in over}) > 1:
            # Its knob turned mid-over (SHACK-XW21): the downlink moved on
            # its way down, and which frequency each find belongs to is a
            # guess the round trip makes. Measured again next over.
            self.log.info("TX lock: the IC-9700 changed frequency during the over; not corrected from it")
            return
        owns = [o for _h, _e, o, _f in over]
        mid = float(statistics.median(owns))
        agree = [o for o in owns if abs(o - mid) <= RIG_AGREE_HZ]
        if 2 * len(agree) <= len(owns) or len(agree) < RIG_AGREE_MIN:
            self.log.info("TX lock: the IC-9700's over measured %s Hz, too scattered to correct from",
                          ", ".join(f"{e:+.0f}" for _h, e, _o, _f in over))
            return
        own = float(statistics.median(agree))
        with self.lock:
            corr = self.st["rigTxCorr"]
        err = own + corr                     # where it landed against the dial
        unsteady = self._rig_rx_unsteady()
        if unsteady:
            self.log.info("TX lock: the IC-9700 landed %+.1f Hz off; not corrected: %s", err, unsteady)
            return
        if self.rig_held:
            self.log.info("TX lock: the IC-9700 landed %+.1f Hz off (own error %+.1f Hz); not corrected: %s",
                          err, own, self.rig_held)
            return
        last = self.rig_unverified
        if last is not None:
            was_own, before, step = last
            if abs(own - was_own) > max(RIG_VERIFY_HZ, 0.5 * abs(step)):
                self._rig_hold(own, was_own, before, step)
                return
            self.rig_unverified = None
        cap = float(self.st["rigTxCorrMaxHz"])
        if abs(own) > cap:
            # Refused, not clamped: a correction this size is either a
            # radio that needs its reference seen to, or a measurement of
            # something that is not its signal, and half of it is no
            # answer to either.
            self.log.info("TX lock: the IC-9700 landed %+.1f Hz off, own error %+.1f Hz, beyond the %.0f Hz "
                          "limit; rigTxCorr left at %+.1f Hz", err, own, cap, corr)
            self.tx_warn("rig-txlock", _("TX lock measured the IC-9700 {err:+.0f} Hz off, more than the {cap:.0f} "
                                         "Hz it may correct (Settings › Transmitter): not corrected. Check the "
                                         "radio's frequency reference").format(err=-own, cap=cap), "warn")
            return
        self.tx_clear("rig-txlock")
        target = -own
        step = max(-RIG_STEP_MAX_HZ, min(RIG_STEP_MAX_HZ, target - corr))
        with self.lock:
            self.st["rigTxCorr"] = corr + step
            first = not self.st["rigTxCorrTrusted"]
            self.st["rigTxCorrTrusted"] = True
            self.dirty_locks = True
            self.pending["rigTxCorr"] = self.st["rigTxCorr"]
            self.pending["rigTxCorrTrusted"] = True
        self.rig_unverified = (own, corr, step)
        self.monitor.trusted = True
        self.log.info("TX lock: the IC-9700 landed %+.1f Hz off, own error %+.1f Hz (%d of %d measurements); "
                      "rigTxCorr now %+.1f Hz", err, own, len(agree), len(owns), self.st["rigTxCorr"])
        if step != target - corr:
            self.toast(_("TX lock: the IC-9700 landed {err:+.0f} Hz off; corrected by {step:+.0f} Hz for the "
                         "next over, the most one over moves it (rigTxCorr {corr:+.0f} Hz)").format(
                err=err, step=step, corr=self.st["rigTxCorr"]), "info")
        elif abs(err) >= 5.0 or first:
            self.toast(_("TX lock: the IC-9700 landed {err:+.0f} Hz off; corrected for the next over "
                         "(rigTxCorr {corr:+.0f} Hz)").format(err=err, corr=self.st["rigTxCorr"]), "info")

    def _rig_rx_unsteady(self) -> str:
        """Why the receive reference cannot be trusted for the over just
        ended ("" when it can): RIG_RX_SETTLED_S."""
        since, corr0 = self.rig_rx
        s = self.st
        if s["beaconMode"] != "auto" or s["rxLock"] != "locked" or not s.get("beaconUsed"):
            return "beacon lock is not locked on a beacon in Auto"
        if since is None or self.rx_steady_since != since:
            return "beacon lock was not steady through the over"
        if self.rig_rx_t0 - since < RIG_RX_SETTLED_S:
            return f"beacon lock had held for under {RIG_RX_SETTLED_S:.0f} s when it keyed"
        if abs(s["rxCorr"] - corr0) > RIG_RX_MOVE_HZ:
            return f"the receive correction moved {s['rxCorr'] - corr0:+.0f} Hz during the over"
        return ""

    def _rx_reference_changed(self) -> None:
        """The operator changed the receive reference (a correction, the
        beacon, beacon lock's mode, a converter). The clock of a steady
        lock starts again, and the IC-9700's correction is searched for
        widely next over and has nothing waiting to be verified: what was
        measured before was measured through the old reference. Its value
        is kept - the transmitter did not change, and 0 is no truer."""
        self.rx_steady_since = None
        if self.ext is None:
            return
        self.rig_unverified = None
        with self.lock:
            self.st["rigTxCorrTrusted"] = False
            self.dirty_locks = True
            self.pending["rigTxCorrTrusted"] = False
        if not self.st["keyed"]:
            self.monitor.trusted = False

    def _rig_hold(self, own: float, was_own: float, before: float, step: float) -> None:
        """The last correction was not seen to take effect: undo it, and
        stop correcting until TX lock is switched off and on."""
        with self.lock:
            self.st["rigTxCorr"] = before
            self.dirty_locks = True
            self.pending["rigTxCorr"] = before
        self.rig_unverified = None
        self.rig_held = (f"a {step:+.0f} Hz correction did not show on the downlink "
                         f"(own error {was_own:+.0f} Hz, then {own:+.0f} Hz)")
        self.log.warning("TX lock: stopped correcting the IC-9700: %s; rigTxCorr back to %+.1f Hz",
                         self.rig_held, before)
        text = _("TX lock stopped correcting the IC-9700: its {step:+.0f} Hz correction did not show on the "
                 "downlink, so the signal it measured may not be yours. Correction put back to {corr:+.0f} Hz; "
                 "switch TX lock off and on to try again").format(step=step, corr=before)
        self.tx_warn("rig-txlock", text, "warn")
        self.toast(text, "warn")

    def _rig_corr_check(self) -> None:
        """A rigTxCorr beyond rigTxCorrMaxHz - one 0.1.18 ran up and saved,
        or a limit just lowered under it - is not used: it goes back to 0
        (the radio as it is), and TX lock finds it afresh within the limit."""
        corr, cap = self.st["rigTxCorr"], float(self.st["rigTxCorrMaxHz"])
        if abs(corr) <= cap:
            return
        with self.lock:
            self.st["rigTxCorr"] = 0.0
            self.st["rigTxCorrTrusted"] = False
            self.dirty_locks = True
            self.pending["rigTxCorr"] = 0.0
            self.pending["rigTxCorrTrusted"] = False
        self.monitor.trusted = False
        self.log.warning("TX lock: rigTxCorr %+.1f Hz is beyond the %.0f Hz limit; reset to 0", corr, cap)
        self.toast(_("The IC-9700's stored correction ({corr:+.0f} Hz) is more than the {cap:.0f} Hz TX lock may "
                     "correct: reset to 0").format(corr=corr, cap=cap), "warn")

    def _rig_lock_reset(self) -> None:
        """TX lock switched (or the external radio started): a fresh start,
        with nothing waiting to be seen and no hold."""
        self.rig_unverified = None
        self.rig_held = ""
        self.tx_clear("rig-txlock")

    def _rig_measure(self, res: dict, out: dict, vs: float | None) -> None:
        """One confident TX-lock measurement during an external over:
        kept for the correction at its end, never applied now. With it,
        the radio's own error: where the signal landed against where the
        frequency the 9700 reports puts it uncorrected - what the 9700 was
        actually on, so a correction it never received is not counted as
        made."""
        how, err = res.get("how"), res["err"]
        if how in RIG_MEASURED and self._rig_on_beacon(err):
            # Never ours: NB does not key there, and the guard would refuse
            # it. A short CAT line whose signal never came down matched the
            # keyed lower beacon 41 kHz away, three times alike, and moved
            # rigTxCorr 2 kHz (the CAT PTT tests, which send no signal).
            how = "beacon"
        s = self.st
        f = s.get("rigFreq")
        if self.ext is not None and f and not self.ext.plan.problem():
            own = s["txDial"] + err - bandplan.dl(self.ext.plan.ul_of(f))
        else:
            f, own = None, err - s["rigTxCorr"]
        self.rig_over.append((how, err, own, f))
        if how in RIG_MEASURED:
            # Landed: found, off the dial by txErr, corrected when the over ends.
            self._status(txLockState="locked" if abs(err) < 25 else "landed")
        # The over-beacon warning is _level_warn's; NB only warns, never
        # changes the radio's power.
        out.update(applied=None, rigTxCorr=self.st["rigTxCorr"])

    def _rig_on_beacon(self, err: float) -> bool:
        """Whether this over's signal, moved by `err`, would sit on a
        beacon (a segment the band plan keeps clear of everyone)."""
        req = self.tx_req if self._cat_now() else None
        dial = self.st["txDial"]
        lo, hi = (req or {}).get("occupied") or (dial - 50.0, dial + 50.0)
        return any(allowed is None and "beacon" in label and lo + err < b_hi and hi + err > b_lo
                   for b_lo, b_hi, label, allowed, _bw in bandplan.SEGMENTS)

    def _rig_guard(self, data: bool | None) -> None:
        """Judge where the external radio is aimed as NB judges itself.
        Advisory only: NB cannot stop it being keyed, and says so."""
        if data is not None:
            self.rig_data = bool(data)
        s = self.st
        why = ""
        aim, on_air = s.get("rigAimDl") or 0.0, s.get("rigMode") or ""
        if s.get("rigLink") == "ok" and aim and on_air:
            why = judge(on_air, aim, s["mode"], self.rig_data, s["txFilterLo"], s["txFilterHi"])
        self._status(rigTxBlocked=why)

    # ------------------------------------------- CAT PTT for digital overs
    # ohsnb/extrig.py CatPtt and its module docstring say what and why. The
    # engine's transmit loop runs a CAT over through the hooks below: the
    # audio to the 9700's sound card (_tx_audio_out), keyed early by the
    # PA delay (_tx_key_lead), key-up and key-down by CatPtt, and the link
    # checked every block (_tx_follow). The Pluto is never touched.
    def _cat_req(self, mode: str, req: dict | None) -> bool:
        """Whether an over `req` in `mode` is one NB keys the external radio
        for: CAT PTT on, a CAT mode, and a rendered message from send() in
        that same mode (never PTT, a voice memory or a tune) - or the setup
        assistant's level-set tone (ohsnb/rigsetup.py), which is made to go
        exactly this way. With req None (the idle status) the question is
        whether a send would be."""
        if self.ext is None or not self.st.get("rigCatPtt") or mode not in CAT_MODES:
            return False
        if req is None:
            return True
        source = str(req.get("source", ""))
        ours = source.startswith("send:") or (source == "setup:level" and req.get("level_set") is True)
        return ours and req.get("mode") == mode

    def _cat_now(self) -> bool:
        req = self.tx_req
        return bool(req and req.get("cat")) and self.ext is not None

    def _cat_guard(self, mode: str, dial: float, occupied) -> str:
        """The checks a CAT over passes on top of the shared ones: the
        Pluto's own (gain, its LO plan, its converter) do not apply, the
        9700's do. Under self.lock: reads state only, no I/O."""
        s = self.st
        ext = self.ext
        name = RIG_NAME[self.cfg["txRadio"]]
        if self.rig_setup_busy:
            return _("The {name} setup assistant is using the radio: wait for it to finish").format(name=name)
        if s.get("rigLink") != "ok":
            return f"The {name} is not answering (link {s.get('rigLink')}): NB keys it only while it does"
        # The link's own latest word, not the rigKeyed status: that lags a
        # poll behind NB's own confirmed unkey, and refused the next line
        # of a PSK QSO typed straight after the last.
        if ext.link.keyed and not s.get("rigCatKeyed"):
            return f"The {name} is already transmitting"
        if not s.get("rigTxAudioOut"):
            return f"Choose the {name}'s sound device (Settings > Transmitter) to send digital modes through it"
        why = ext.plan.problem()
        if why:
            return why
        want = ext.want()
        if want is None or int(round(s.get("rigFreq") or 0.0)) != want:
            return f"The {name} is not on the transmit frequency yet"
        lo, hi = occupied or self._occupied(mode, dial)
        why = self._uplink_refusal(bandplan.ul(lo), bandplan.ul(hi))
        if why:
            return why
        width = None if occupied else bandplan.SIGNAL_WIDTH.get(mode)
        why = bandplan.tx_blocked(lo, hi, mode, width=width)
        if why:
            return why
        if mode != "cw":
            # Where the radio is aimed, judged as it will be once keyed:
            # in the data variant. (A CW line is a tone in USB-D whose
            # carrier the occupied band above has judged as CW.)
            why = judge("usb", s.get("rigAimDl") or 0.0, mode, True, s["txFilterLo"], s["txFilterHi"])
            if why:
                return why
        mi = ext.link.mod_input
        why = mod_input_problem((mi or {}).get("data", ""))
        if why:
            return why
        return ""

    def _tx_blocked(self, occupied, req=None) -> str:
        # A CAT over does not need the receive device to be able to
        # transmit: the IC-9700 does (an RTL-SDR receiver is fine).
        mode = self._judged_mode(req)
        if self.running and self._cat_req(mode, req):
            return self._tx_guard(mode, self._tx_dial(self.st), occupied, req)
        return super()._tx_blocked(occupied, req)

    def _tx_audio_out(self, req: dict):
        if not self._cat_req(req["mode"], req):
            return None
        req["cat"] = True
        # The level set starts below the stored level and steps it itself.
        db = req.get("level_db", self.st["rigTxAudioDb"])
        # The setup assistant's sound-device test (rigsetup.which_codec)
        # plays its tone into each candidate in turn; only its tone may
        # name a device, and every over still needs one saved (_cat_guard).
        device = self.st["rigTxAudioOut"]
        if req.get("level_set") is True and req.get("audio_out"):
            device = str(req["audio_out"])
        return self.audio.open_tx_out(device, 10 ** (db / 20))

    def _tx_key_lead(self, req: dict) -> float:
        return self.st["rigPttDelayMs"] / 1000.0 if req.get("cat") else 0.0

    def _over_facts(self, req: dict) -> str:
        s = self.st
        if req.get("cat"):
            sink = req.get("sink")
            out = getattr(sink, "describe", None)
            device = out() if callable(out) else repr(getattr(sink, "device", s["rigTxAudioOut"]))
            return (f"IC-9700 by CAT, audio to {device} at {req.get('level_db', s['rigTxAudioDb']):+.1f} dB, "
                    f"PTT delay {s['rigPttDelayMs']} ms, tail {s['rigPttTailMs']} ms")
        return (f"{self.cfg.get('device')} at {bandplan.ul(s['txDial']) + s['txCorr']:.0f} Hz uplink, "
                f"TX gain {s['txGain']:+.1f} dB, txCorr {s['txCorr']:+.0f} Hz")

    # ---------------------------------------------------------- dish alignment
    # The window (ohsnb/ui/dishmeter.py) opens and closes it; the receive
    # thread measures (_rx_wide) and holds the gain; the phone page runs on
    # threads of its own and reads only the status.
    def dish_open(self) -> None:
        """Open dish alignment: measure the middle beacon and the
        transponder, hold the receive gain where it is, refuse transmit
        until dish_close(). Raises ValueError (a sentence) while
        transmitting. Opening it twice is opening it once."""
        with self.lock:
            if self.st["keyed"] or self.st.get("rigKeyed"):
                raise ValueError(_("Transmitting: dish alignment opens once you are back on receive"))
            if self.dish_on:
                return
            self.dish_on = True
            self.dish_meter = None
        self.dish_best.reset()
        self._status(dishOpen=True, dishSnr=None, dishBest=None, dishRise=None, dishWhere="", dishGain="",
                     dishPhoneError="")
        self._derive()
        if self.st["dishPhone"]:
            self._dish_phone(True)
        self.log.info("dish alignment opened")

    def dish_close(self) -> None:
        """Close it: the gain back to the operator's setting, the phone page
        stopped (and off for next time), transmit allowed again."""
        with self.lock:
            if not self.dish_on:
                return
            self.dish_on = False
            self.dish_meter = None
            held, self.dish_fixed = self.dish_fixed, None
            self.reconf = True
            self.st["dishPhone"] = False
            self.pending["dishPhone"] = False
        self._dish_phone(False)
        self._status(dishOpen=False, dishGain="", dishWhere="", dishHeldDb=None)
        self._derive()
        if held is not None:
            self.log.info("dish alignment closed: receive gain back to the AGC (%s), from %g dB held",
                          self.st["rxGainMode"], held)
        else:
            self.log.info("dish alignment closed")

    def dish_reset(self) -> None:
        """Forget the best figure (the next measurement starts it again)."""
        self.dish_best.reset()
        self._status(dishBest=None)

    def dish_snapshot(self) -> dict:
        """What the phone page shows."""
        with self.lock:
            s = self.st
            out = {"open": self.dish_on, "snr": s["dishSnr"], "best": s["dishBest"], "rise": s["dishRise"],
                   "where": s["dishWhere"]}
        out["tone"] = tone_hz(out["snr"])
        return out

    def _dish_phone(self, on: bool) -> None:
        old, self.dish_page = self.dish_page, None
        if old is not None:
            old.stop()
        if not on:
            self._status(dishUrls="")
            return
        page = PhoneServer(self.st["dishPort"], self.dish_snapshot, self.dish_reset)
        try:
            page.start()
        except OSError as e:
            why = (f"Port {self.st['dishPort']} is in use by another program: choose another"
                   if getattr(e, "errno", None) in (98, 48, 10048) else f"The phone page could not start: {e}")
            with self.lock:
                self.st["dishPhone"] = False
                self.pending["dishPhone"] = False
            self._status(dishUrls="", dishPhoneError=why)
            return
        self.dish_page = page
        self._status(dishUrls=", ".join(page.urls()), dishPhoneError="")

    def _rx_gain_wanted(self, s: dict) -> tuple:
        if self.dish_fixed is not None:
            return "manual", float(self.dish_fixed)
        return super()._rx_gain_wanted(s)

    def _dish_hold_gain(self) -> None:
        """On the receive thread: hold the gain where it is now. Never
        through set(): the operator's own setting stays as it was, so
        closing the tool, or the program stopping with it open, leaves
        their gain control exactly as they chose it."""
        s = self.st
        if self.play is not None:
            self.dish_fixed = None
            self._status(dishGain="Playing a recording: its gain was fixed when it was recorded.")
            return
        if s["rxGainMode"] == "manual":
            self.dish_fixed = None
            self._status(dishGain=f"Receive gain is manual at {s['rxGain']:g} dB already, and stays there.")
            return
        try:
            now = self.dev.rx_gain_now()
        except Exception:  # noqa: BLE001 - a radio that cannot say is handled below
            now = None
        if now is None:
            g = float(s["rxGain"])
            why = _("Receive gain held at {db:g} dB (manual), the Receiver gain setting - the radio could not "
                    "say where its AGC was. The AGC is back when you close this.").format(db=g)
        else:
            g = float(now)
            why = _("Receive gain held at {db:g} dB (manual), where the AGC had it. The AGC is back when you "
                    "close this.").format(db=g)
        # Said where it matters, not only in the dialog: the log (until
        # 17/10/2026 it said "dish alignment opened" and nothing about the
        # gain), and a recording running, whose level the hold changes -
        # the recording itself marks it (REC_STATES, dishHeldDb).
        recording = self.rec is not None
        if recording:
            why += " " + _("A recording is running: the hold is marked in it.")
        self.log.info("dish alignment: receive gain held at %g dB manual (%s); the Receiver gain setting is "
                      "unchanged%s", g, "the radio's AGC had it there" if now is not None else
                      "the radio could not say where its AGC was", "; marked in the recording running"
                      if recording else "")
        self.dish_fixed = g
        self.rx_gain_applied = None
        self.reconf = True
        self._status(dishGain=why, dishHeldDb=g)

    def _rx_wide(self, x) -> None:
        # Kept for the over-power watch, which _rx_monitor feeds with this
        # block's spectra once they exist.
        self.wide_x = x
        if not self.dish_on:
            return
        m = self.dish_meter
        if m is None or m.fs != self.geo.fs:
            m = self.dish_meter = DishMeter(self.geo.fs)
            self._dish_hold_gain()
        s = self.st
        middle = bandplan.BEACONS["middle"]["ref"]
        locked = s["beaconMode"] == "auto" and s["rxLock"] == "locked"
        rep = m.feed(x, self._off(middle), (self._off(bandplan.DL_LO), self._off(bandplan.DL_HI)), locked)
        if rep is None:
            return
        best = self.dish_best.see(rep["snr"])
        self.dish_tone.target = tone_hz(rep["snr"])
        if rep["snr"] is None:
            where = "No beacon measured"
        elif locked:
            where = "Where beacon lock has the middle beacon"
        else:
            where = (f"Beacon lock has not got it: the strongest signal within ±15 kHz, "
                     f"{rep['offset'] / 1000:+.1f} kHz from where the beacon should be")
        self._status(dishSnr=rep["snr"], dishBest=best, dishRise=rep["rise"], dishWhere=where)

    def _rx_heard(self, heard):
        # The tone in place of the receive audio, through the same volume
        # and mute: a pitch is easier to follow alone than under a station.
        if self.dish_on and self.st["dishTone"]:
            return self.dish_tone(len(heard))
        return heard

    # ------------------------------------------------------------------ transmit
    def _tx_guard(self, mode: str, dial: float, occupied, req: dict | None = None) -> str:
        s = self.st
        if self.dish_on:
            # Peaking a dish means a hand near the feed and a gain held
            # where an AGC would not be: never with the transmitter on.
            return "Dish alignment is open: close it to transmit"
        if self.cfg.get("txRadio", "sdr") != "sdr":
            if self._cat_req(mode, req):
                return self._cat_guard(mode, dial, occupied)
            name = RIG_NAME[self.cfg["txRadio"]]
            if s.get("rigCatPtt") and mode in CAT_MODES:
                return (f"The {name} is keyed by NB only for its own digital messages; for anything else, key it "
                        "on the radio")
            if s.get("rigCatPtt"):
                return (f"The {name} is the transmitter (Settings > Transmitter): NB keys it only for digital "
                        "modes; for voice, key it on the radio")
            return f"The {name} is the transmitter (Settings > Transmitter): key it on the radio"
        if mode == "am":
            return "AM is receive-only (for listening to beacons)"
        lo, hi = occupied or self._occupied(mode, dial)
        why = self._uplink_refusal(bandplan.ul(lo), bandplan.ul(hi))
        if why:
            return why
        # With nothing measured - idle (what the TX button and its tooltip
        # show) and plain PTT - a digital mode is judged by its own signal's
        # width, anywhere in the transmit passband. Plain PTT in a digital
        # mode sends the microphone input, which for these modes is another
        # program's audio through a loopback device (ENGINE-API.md, ptt):
        # an FT4 signal, not speech; and FreeDV's PTT sends its modem. They
        # were judged by the SSB passband's 2.4 kHz instead: after an FT4
        # send that had measured itself at 85 Hz and gone out, txBlocked
        # went back to "narrow digimodes allows 500 Hz; this signal is
        # 2400 Hz wide" - true of nothing FT4 sends - and PTT for WSJT-X
        # through a loopback was refused in that segment altogether.
        if occupied:
            width = None
        elif mode == "freedv":
            width = bandplan.FREEDV_WIDTH.get(s["freedvMode"])
        elif mode == "hsmodem":
            width = bandplan.HSMODEM_WIDTH.get(int(s["hsSpeed"]))
        else:
            width = bandplan.SIGNAL_WIDTH.get(mode)
        why = bandplan.tx_blocked(lo, hi, mode, width=width)
        if why:
            return why
        if s["txGain"] > s["txGainCeiling"]:
            return "Transmit gain is above the ceiling"
        c = nbconv.tx_converter(s)
        why = nbconv.tx_ok(c, s.get("txConverter", ""), "Pluto's transmit")
        if why:
            return why
        if c is not None and s["txGain"] > self._gain_cap(s) + 1e-9:
            return (f"Transmit gain {s['txGain']:g} dB puts about {nbconv.drive_dbm(s['txGain']):.1f} dBm into "
                    f"{c.title}, more than its {c.max_drive_dbm:g} dBm")
        target = bandplan.ul(dial) + s["txCorr"]
        if plan_tx_lo(target, self.dev.fs, self.tx_lo) is None:
            return (f"At {self.dev.fs / 1000:.0f} kS/s this uplink cannot be reached without putting the "
                    f"transmit LO inside the passband; use 1.2 MS/s")
        return ""

    def _uplink_refusal(self, lo: float, hi: float) -> str:
        """'' if the licence in force lets the operator's class transmit to
        QO-100 on [lo, hi] (uplink Hz); else why not. A class with no 13 cm
        (Germany's N, Sweden's insteg...) or a licence whose 13 cm is not
        amateur-satellite locks the uplink. Where the licence or class is
        not known yet - no callsign, a country not in the dataset, no class
        chosen - nothing is refused here: the check cannot be made, not
        failed, and _licence_warning puts that on the transmit card instead
        (Brian, 08/10/2026 - NB warns rather than locking, unlike Radio's
        guard; see _licence_warning).

        Answered by the shared dataset for the station profile
        (ohscore/txguard.py; it was ohscore/licences satellite_uplink). No
        mode and no width: the plan's own questions are tx_blocked's, and
        both read the same plan, so where this one does reach the plan (a
        beacon, outside the transponder) the sentence is the same."""
        v = txguard.GUARD.check(txguard.profile(self.st), lo, hi, satellite="qo100-nb", signal_bw=0.0)
        return "" if v.licence_unknown else v.refused

    def _derive(self):
        super()._derive()
        self._licence_warning()

    def _licence_warning(self) -> None:
        """The transmit card's standing warning (Engine.tx_warn, "licence")
        for as long as the licence in force cannot be worked out, or no
        class has been chosen under it: the uplink guard (_uplink_refusal)
        cannot check anything then, and says nothing on its own because it
        only ever refuses. Brian, 08/10/2026: warn, don't lock - a class
        was never asked for before this check existed, so every installed
        NB has none, and locking their transmit on an update would stop
        all of them rather than the few who should see this. Clears as
        soon as a class is chosen under a known licence."""
        if self.receive_only:
            # A run started --receive-only refuses every over whatever the
            # licence says, so "transmitting is not refused" would be false;
            # the card says why it cannot transmit instead (seen on the Mac,
            # 17/10/2026, beside a TX button that already read "unavailable").
            self.tx_warn("licence", RECEIVE_ONLY_REFUSAL, "info")
        elif not txguard.GUARD.in_force(txguard.profile(self.st))["canTransmit"]:
            self.tx_warn("licence", NO_LICENCE_WARN, "warn")
        else:
            self.tx_clear("licence")

    def _station_status(self) -> dict:
        """The `station` status with what NB adds: whether the uplink is
        allowed (and at what power) under the licence in force, and
        QO-100's footprint from here."""
        # Worked out again only when what it depends on changes: _derive
        # runs on every dial step.
        key = repr([self.st.get(k) for k in self.LICENCE_KEYS + ("locator",)])
        if getattr(self, "_station_key", None) == key:
            return self._station_info
        info = super()._station_status()
        notes = list(info.get("notes", []))
        inf = self.licence_in_force()
        if inf.regime is None:
            notes.append(UPLINK_UNCHECKED.format(why=inf.why_none))
        elif not inf.cls or inf.cls not in inf.regime.CLASSES:
            notes.append(UPLINK_NO_CLASS)
        else:
            _allowed, _limit, why = licences.satellite_uplink(inf.regime, inf.cls, bandplan.UL_LO, bandplan.UL_HI,
                                                              licences.condition_answers(inf.regime, self.st))
            if why:
                notes.append(why)
        q = countries.qo100_note(self.st, self.data_dir)
        if q:
            notes.append(q)
        info["notes"] = notes
        self._station_key, self._station_info = key, info
        return info

    def _tx_key_up(self, dev) -> None:
        if self._cat_now():
            self.ext.cat.key_up(self.tx_req.get("start_at") or 0.0, self._tx_halted)
            return
        s = self.st
        dial = self.st["txDial"]
        target = bandplan.ul(dial) + s["txCorr"]
        self.tx_lo = plan_tx_lo(target, dev.fs, self.tx_lo)
        # Through a transmit converter the SDR is tuned to the IF; an
        # inverting one has the engine mirror what it sends (Engine.tx_invert).
        # Everything else - the LO plan, TX lock - stays in uplink terms.
        self.tx_conv = nbconv.tx_converter(self.cfg)
        self.tx_invert = bool(self.tx_conv is not None and self.tx_conv.inverted)
        dev.set_tx_gain(-89.75)
        dev.set_tx_freq(self._radio_tx(self.tx_lo))
        self.tx_src.freq = target - self.tx_lo
        dev.tx_start()
        dev.set_tx_gain(s["txGain"])

    def _on_keyed(self) -> dict:
        if self._cat_now():
            # TX lock and the level guard follow the radio's own transmit
            # state from its link (_rig_keyed), as for a hand-keyed over.
            return {}
        self.monitor.set_keyed(True, self.rx_samples / self.geo.fs)
        self._level_new_over()
        return {"txLockState": "searching", "vsBeacon": None}

    def _tx_follow(self, dev) -> bool:
        if self._cat_now():
            # The IC-9700 is not retuned while it transmits (extrig.py);
            # what matters each block is that its link is still there.
            if self.ext.link.state != "ok":
                self._unkey(_("Unkeyed: lost the IC-9700 link mid-over. NB cannot confirm the radio stopped "
                              "transmitting - check it, and release it there if it is still on the air"), "error",
                            "link lost")
                return False
            return True
        # Follow the dial and txCorr (phase-continuous); move the LO only if
        # the signal would leave the NCO's reach.
        dial = self.st["txDial"]
        target = bandplan.ul(dial) + self.st["txCorr"]
        lo = plan_tx_lo(target, dev.fs, self.tx_lo)
        if lo is None:
            self._unkey("Unkeyed: that uplink cannot be reached at this sample rate", "warn", "uplink unreachable")
            return False
        if lo != self.tx_lo:
            self.tx_lo = lo
            dev.set_tx_freq(self._radio_tx(lo))
        self.tx_src.freq = target - lo
        return True

    def _radio_tx(self, ul: float) -> float:
        """What the SDR is tuned to for uplink `ul`."""
        return self.tx_conv.radio(ul, tx=True) if self.tx_conv is not None else ul

    def _tx_sent(self, dev, bb) -> None:
        sink = (self.tx_req or {}).get("sink") if self._cat_now() else None
        if sink is not None:
            # A CAT over: on air once the 9700's sound card has played what
            # it already holds (TxOut.tx_queued counts the card's own
            # buffer). The radio's own audio-to-RF delay is not counted;
            # the monitor matches 1 s averages of FT8's 160 ms symbols, which
            # a few tens of ms do not move.
            t_air = self.rx_samples / self.geo.fs + sink.tx_queued()
        else:
            t_air = self.rx_samples / self.geo.fs + dev.tx_latency()
        self.monitor.tx(bb, t_air)

    def _tx_key_down(self, dev) -> None:
        if self._cat_now():
            self.ext.cat.key_down(halted=self._tx_halted())
            return
        dev.set_tx_gain(-89.75)
        dev.tx_stop()

    def _on_unkeyed(self) -> dict:
        if self._cat_now():
            return {}
        self.monitor.set_keyed(False, self.rx_samples / self.geo.fs)
        self._level_after_over()
        return {"txLockState": "idle"}
