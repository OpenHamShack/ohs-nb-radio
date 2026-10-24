"""The engine: one object the UI talks to (DESIGN.md "Engine API").

    radio = Radio(cfg)           # an app's Engine subclass; opens nothing, never transmits
    radio.start()                # opens device + audio, starts RX
    radio.set(**changes)         # validated against the app's state registry
    radio.state() -> dict
    radio.ptt(on)                # voice modes key with mic audio; CW keys a carrier
    radio.send(mode, **msg)      # queue a digital transmission
    radio.send_voice(slot)       # a voice memory, through PTT's path (ohscore/keyer.py)
    radio.halt()                 # Escape / Halt TX: RF off now, the queue dropped
    radio.subscribe(kind, maxlen) -> Feed
    radio.heartbeat()            # the UI's timer calls this; the watchdog unkeys without it
    radio.stop()

Threads:
- **rx**: reads the device, runs every receive consumer on each block. It
  never blocks on a consumer: Feeds drop their oldest item instead.
- **tx**: exists only while keyed. Paced by device.write().
- **decode**: mode decoders, fed from a queue, so a slow decoder costs
  decodes, never receive.
- **supervisor**: 10 Hz. The safety timers (TX timeout, dead air, watchdog)
  live here and not in the rx thread, so a stalled device read cannot stop
  them unkeying. It also batches status into the "state" feed and persists
  the config.
- **saver**: only while something is unsaved, running or not: writes the
  operator's changes a second after the last of a burst (three at most),
  so a dial moved while the radio is stopped is not lost (`dirty`).

Two ways an over ends. A **normal end** - the message is all sent, PTT
is released - stops taking audio and lets the device send what it already
holds before it is stopped (`_tx_drain`), so the last element, character
or syllable is on air; `keyed` stays true, and the PTT sequencer holds,
until the device's queue is empty or DRAIN_MAX has passed. An **emergency
unkey** - `halt()` (Escape, Halt TX, Stop), the watchdog, the time-out,
dead air, a guard refusal, a protection trip, a failed device, `stop()` -
goes through `_unkey`, which stops it at once and drops the queue: the
drain checks for it continuously, so an emergency during a drain is still
immediate.

Safety (DESIGN.md, non-negotiable): keying happens only from ptt()/send()
(and send_voice(), which is ptt() with a recording for a microphone);
start, restart, reconnect and set() never key. Every key-up passes
`_tx_blocked()` (device can transmit, then the app's guard), and is
re-checked while keyed when the dial moves.

`Engine` is everything above that is the same for QO-100 NB and OpenHamShack
HAM: it was ohsnb.radio.Radio with the QO-100 parts taken out
(docs/ham/DESIGN-HAM.md section 2.4). An app subclasses it and supplies,
as class attributes, its state registry, config, device registry and
feed kinds, and, as methods, what differs between a satellite transponder
and a terrestrial band:

- the frequency model: `_off(dial)` (offset from the IQ stream's DC of a
  dial frequency), `_dial_at(off)` (its inverse), `_initial_tuning()` and
  `wide_span()` (the dial frequencies the wide scope covers);
- the dials: `_rx_dial(s)` and `_tx_dial(s)` (defaults: vfo + RIT; txVfo
  when split, else vfo, + XIT - HAM adds a repeater shift and reverse);
- the transmit guard: `_tx_guard(mode, dial, occupied, req)`;
- transmit choreography and power: `_tx_key_up`, `_tx_follow`, `_tx_sent`,
  `_tx_draining`, `_tx_key_down`, and `_adjust_set` / `_after_set` around
  `set()`;
- its own receive consumers: `_start_consumers`, `_configure_consumers`,
  `_rx_track` (before the channels, so they use this block's correction),
  `_rx_monitor` (after them) and `_rx_done`; `_rx_wide(x)` (the wideband
  block itself, as the wide scope gets it); `_demodulate` (the VFO
  channel to audio: an app with a mode the core's demodulator lacks, such
  as HAM's FM, takes it from its own channel), `_rx_audio_gain` (half
  duplex mutes receive while keyed) and `_rx_heard` (what the speaker
  gets in place of the receive audio: NB's dish-alignment tone);
- the transmitter's modulator and the stream that places it:
  `_tx_chain(req)`, and `_mode_caps(info)` for what the app's own modes
  can do; or, for an over another radio transmits from its own sound card
  (NB's IC-9700 by CAT PTT, 12/10/2026), `_tx_audio_out(req)` and
  `_tx_key_lead(req)`;
- its own status: `_derived`, `_start_status`, `_on_keyed`, `_on_unkeyed`,
  `_meter_extra`, `_supervise_status`, `_save_extra`; and the ADIF fields
  of a log record, `_adif_fields`.

The defaults here are what an app with nothing to add would want, so a
hook is only written where an app differs.
"""
from __future__ import annotations

import contextlib
import json
import logging
import math
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from . import audio as audio_mod
from . import diag
from . import host
from . import hostlibs
from . import sigmf
from . import modes_glue, sdr
from .decoders import Decoders, Refused
from . import countries
from . import dxcc
from . import pskreporter
from . import rxprefetch
from .config import DEVICE_WHY, RECEIVE_ONLY, RECEIVE_ONLY_REFUSAL
from .devices import DeviceError
from .i18n.text import _
from .modegroups import JS8_DEFAULT_SPEED, JS8_SPEEDS
from .modegroups import label as mode_label

from .dsp import autoaudio, autotune, morse
from .dsp.bank import Analysis, Channel, Geometry, Source, Synthesis
from .dsp.demod import Demod, NoiseBlanker, passband
from .dsp.nr import NoiseReduction
from .dsp.mod import SsbMod
from .dsp.multirate import Interpolator
from .dsp.dcblock import DcBlocker
from .dsp.spectrum import Line, Scope, wide_nfft
from .keyer import Keyer, VOICE_MODES
from .logbook import Logbook
from . import station as station_mod
from .memories import Memories

AUDIO_RATE = 12_000


class Feed:
    """Bounded, drop-oldest queue. The engine puts and never blocks; the UI
    drains on a timer. `dropped` counts what a slow consumer missed."""

    def __init__(self, kind: str, maxlen: int):
        self.kind = kind
        self.q: deque = deque(maxlen=max(1, int(maxlen)))
        self.lock = threading.Lock()
        self.dropped = 0
        self.last_drain = time.monotonic()
        self.closed = False

    def put(self, item) -> None:
        with self.lock:
            if len(self.q) == self.q.maxlen:
                self.dropped += 1
            self.q.append(item)

    def drain(self, max_items: int | None = None) -> list:
        with self.lock:
            self.last_drain = time.monotonic()
            if max_items is None or max_items >= len(self.q):
                out = list(self.q)
                self.q.clear()
            else:
                out = [self.q.popleft() for _ in range(max_items)]
            return out

    def get(self):
        with self.lock:
            self.last_drain = time.monotonic()
            return self.q.popleft() if self.q else None

    def __len__(self):
        return len(self.q)


class TxRefused(ValueError):
    """Keying refused; the message is the operator-readable reason."""


class ReceiverHeld(ValueError):
    """set() refused a change that would tune the receiver while a decoder
    session holds it (Engine.hold_receiver); the message is the sentence.
    The store's api/set answers it 409 `receiver_busy`."""

    code = "receiver_busy"


class SpanPinned(ValueError):
    """set() refused to tune the dial out of the span the background
    decoder sessions hold (Radio.pin_plan; RADIO-SDR-PLAN §8.5): the
    message is the sentence, `sessions` the sessions it would stop
    ({id, decoder, freqHz, label}). The store's api/set answers it 409
    `span_pinned`; set(drop_sessions=True) stops them and tunes."""

    code = "span_pinned"

    def __init__(self, sentence: str, sessions: list[dict], freq: float | None = None):
        super().__init__(sentence)
        self.sessions = sessions
        self.freq = freq          # the receive dial the change would have given


SLOT_SEC = {"ft8": 15.0, "ft4": 7.5, "q65": 60.0, "js8": 15.0}
# Where in its slot a transmission normally starts. Q65-60 starts 1 s in,
# as WSJT-X's Modulator starts it and its decoder expects (DT 0); it was
# 0.5 s here until 10/10/2026, which put every Q65 transmission at DT -0.5.
SLOT_LEAD = {"ft8": 0.5, "ft4": 0.5, "q65": 1.0, "js8": 0.5}
# How long after its normal start a transmission may still begin. FT8's
# decoder looks for a signal up to 2.5 s either side of the nominal 0.5 s
# start (WSJT-X lib/ft8/sync8.f90: "Maximum sync correlation lag +/- 2.5s
# relative to 0.5s TX start time"), and WSJT-X's last decoding pass is 14.7 s
# into the slot (WSJT-X 2.2.0 release notes: passes at 11.8, 13.5 and 14.7 s).
# Starting at most 1.5 s late -- 2.0 s into the slot, DT +1.5 -- the 12.64 s
# transmission is over by 14.64 s, before that last pass, with a second of
# the DT search left for the other station's clock error. FT4's decoder
# searches DT -1.0 .. +1.0 s (lib/ft4_decode.f90: ib from -344 to 1012 at
# 666.67 Hz, xdt = ib/666.67 - 0.5), i.e. DT 0 is a start 0.5 s into the
# slot, so FT4 starts there as WSJT-X's does (it once started at 0.0 s,
# DT -0.5: decodable, but half its tolerance spent before any clock error).
# 0.5 s late is DT +0.5, and the 5.04 s transmission still ends by 6.04 s.
# Q65-60A: WSJT-X searches DT -1 .. +1 s (q65.f90 q65_dec0: lag1 =
# -1/dtstep, lag2 = 1/dtstep + 0.9999, 14 steps of 0.075 s), and only an
# operator who ticked "Decode at 52 s" (its EME delay, which jt9 run from
# the command line also sets) searches to +5.5 s. So 1 s late, DT +1, is
# the most a station on default settings still decodes; it was 3 s here
# (a guess) until 10/10/2026.
# js8: each frame is an over (ohscore/modes/js8.py), started 0.5 s in as
# JS8Call's modulator starts it (ohsdigi JS8_SUBMODES "normal" start). Its
# 1.5 s late limit is FT8's, not measured: the same frame length and
# decoder search make FT8's own figure the reasonable one. (JS8's decoder searches 62 quarter-symbols either side of
# 0.5 s, lib/js8/js8a_params.f90 JZ - about +-2.5 s, as FT8's.)
SLOT_LATE = {"ft8": 1.5, "ft4": 0.5, "q65": 1.0, "js8": 1.5}
# How far into one of our slots (seconds from the boundary) an over asked
# for with late_start=True may still begin, past SLOT_LATE, by doing what
# WSJT-X's Modulator does with a late start: send the waveform from the
# point the slot's own timing has reached, so the symbols already past are
# dropped and what is sent sits where a punctual over's would (DT ~0).
# Brian's choice (16/10/2026, after Ray's 27 s wait): match WSJT-X more
# closely, about 6 s in. WSJT-X keys up to 75 % into a period; most of that
# is wasted, so the limit is where the other end still decodes, measured
# with ohsdigi's encoder and decoder (a jt9 port) over white noise,
# tools/late_start_decode.py, decodes out of 10 at -6/-10/-14/-18 dB:
#   start 4.0 s: depth 1 10 10 10 2,  depth 3 10 10 10 8
#   start 5.0 s: depth 1  9  5  2 0,  depth 3 10 10  9 3
#   start 6.0 s: depth 1  0  0  0 0,  depth 3  3  4  0 0
#   start 6.0 s, depth 3 with the decoder's own call known (a-priori, on by
#   default in WSJT-X): 10 10 10 2; 6.5 s the same.
# A start 6 s in drops 5.5 s - the first Costas array and 27 of the 58 data
# symbols, the message bits first - so it decodes only where the receiver
# knows part of the message already. That is the case it is for: an answer
# to a CQ, or the next step of a QSO, decoded by a station listening for
# its own call. A blind decode (someone else's CQ) needs it under ~4.5 s.
# FT8 only: FT4's 7.5 s slot leaves no such margin, and Q65/JS8 send
# nothing from the panel that needs it.
SLOT_TRUNCATE = {"ft8": 6.0}


def js8_slot_key(speed: str | None) -> str:
    """The slot tables' key for JS8 at `speed`: "js8" for Normal, as it
    always was, else "js8-<speed>" (ohscore/modegroups.py JS8_SPEEDS)."""
    speed = speed or JS8_DEFAULT_SPEED
    if speed not in JS8_SPEEDS:
        raise ValueError(_("Unknown JS8 speed {speed}").format(speed=repr(speed)))
    return "js8" if speed == JS8_DEFAULT_SPEED else f"js8-{speed}"


# JS8's other four speeds (Brian, 17/10/2026): each its own period, start
# and late limit, from the one table the UI and the decoder read too.
for _name, _sp in JS8_SPEEDS.items():
    if _name != JS8_DEFAULT_SPEED:
        SLOT_SEC[js8_slot_key(_name)] = _sp.period
        SLOT_LEAD[js8_slot_key(_name)] = _sp.start
        SLOT_LATE[js8_slot_key(_name)] = _sp.late


def slot_truncate(now: float, mode: str, period: str | None = None, asked: float | None = None) -> float | None:
    """For a late_start over ready at `now`: the time its audio would have
    started (the current slot's boundary + SLOT_LEAD) when it is too late
    for slot_start's whole-message shift but was asked for (`asked`, else
    `now`) within SLOT_TRUNCATE of the boundary, in a slot of the asked-for
    parity; else None (slot_start decides, as for any over). `asked` is
    when send() was called: rendering takes a few hundred ms, and an over
    asked for at 5.9 s must not be pushed to our next slot, 30 s on, by
    the time its audio is ready."""
    limit = SLOT_TRUNCATE.get(mode)
    if limit is None:
        return None
    slot = SLOT_SEC[mode]
    k = math.floor(now / slot)
    nominal = k * slot + SLOT_LEAD[mode]
    t = now if asked is None else max(asked, k * slot)
    if now <= nominal + SLOT_LATE[mode] or t - k * slot > limit:
        return None
    if period in ("even", "odd") and k % 2 != (0 if period == "even" else 1):
        return None
    return nominal


def slot_start(now: float, mode: str, period: str | None = None) -> float:
    """UNIX time at which an ft8/ft4 transmission queued at `now` should key.

    The slot we are in still counts if the transmission can start within
    SLOT_LATE of its normal start: that is what lets an answer to a CQ
    decoded at the end of one slot go out in the very next one, as WSJT-X's
    does, when the decode (jt9's time on a slow machine included) only
    lands a second or so into it. The earlier rule always waited for the
    *next* slot boundary, so such an answer went a whole cycle late - and
    when the caller asked for the opposite parity to the CQ, two cycles
    late, in the CQ's own parity again. `period` "even"/"odd" picks slot
    parity (slot index = floor(utc / slot length)). Returns `now` itself
    when keying at once is right."""
    slot = SLOT_SEC[mode]
    lead, late = SLOT_LEAD[mode], SLOT_LATE[mode]
    k = math.floor(now / slot)
    if now > k * slot + lead + late:
        k += 1
    if period in ("even", "odd") and k % 2 != (0 if period == "even" else 1):
        k += 1
    return max(now, k * slot + lead)


def mode_tune_target(dial: float, spots: list[tuple[float, float, float]]) -> float | None:
    """Where a mode-pick auto-tune (Engine.set_mode_tuned) should move
    `dial` to, given the mode's usual places `spots` - each (target,
    window_lo, window_hi). None means "leave it": there are no usual
    places here, or `dial` is already inside one of their windows. A mode
    with two usual places (QO-100 FT8's narrow-digi mark and the contest
    zone's) picks whichever target is nearest, so a dial already closer to
    the second is not dragged past it to the first."""
    if any(lo <= dial <= hi for _, lo, hi in spots):
        return None
    if not spots:
        return None
    return min((t for t, _, _ in spots), key=lambda t: abs(t - dial))


class Engine:
    BLOCK_HOPS = 5     # device read = 5 filter-bank hops (75 ms at 1.2 MS/s)
    # A normal end waits for the device's queue (module docstring) for at
    # most what the device said it held plus DRAIN_SLACK, and never longer
    # than DRAIN_MAX: a device that stops taking samples must not hold the
    # transmitter on. The deepest queue is the Pluto's, 375 ms (four 75 ms
    # kernel buffers and a part-block); the simulator's is about 225 ms,
    # the HL2's 60 ms.
    DRAIN_SLACK = 0.25
    DRAIN_MAX = 1.0
    # The rate receive audio is played at: what the sound card, the store's
    # api/audio/rx and its recordings get (the backend's out_rate). The
    # demodulators, the decoders, CW, best audio and every transmit path
    # stay at AUDIO_RATE (12 kHz mono); a mode whose demodulator makes
    # better audio than that hands it over in `heard_hi` (_rx_block), and
    # everything else is upsampled here, once, after noise reduction.
    # Radio plays at 48 kHz (23/10/2026: broadcast FM flat to 15 kHz,
    # and in stereo); QO-100 NB keeps 12 kHz, which is all an SSB
    # transponder's audio has and what its clients already take.
    OUT_RATE = AUDIO_RATE

    # Whether a decoder session may take the whole receiver (DAB; see
    # hold_receiver): an app that retunes its hardware to its dial (Radio)
    # can lend it; QO-100 NB, tuned to one transponder, never does.
    HOLDS_RECEIVER = False
    # Settings a held receiver refuses: each moves what it is tuned to or
    # how it is heard, and the session that holds it decides both.
    HELD_KEYS: tuple = ("vfo", "mode", "rit", "ritOn")
    # What the operator had before a session took the receiver, put back
    # when it lets go (an app adds what tuning away would change with it).
    HOLD_PRIOR: tuple = ("vfo", "mode")
    # Whether background decoder sessions pin the receiver's centre (an
    # app whose centre follows its dial: Radio's pin_plan). QO-100 NB's
    # receiver is on the transponder whatever the dial does, so there is
    # nothing to pin and its sessions keep the `outside` rule.
    PINS_SPAN = False
    # How many bins either side of DC the wide scope fills in for display
    # while the DC blocker runs (_dc_mask): the blocker leaves a residue a
    # bin wide, and a zero-IF receiver's LO phase noise a skirt of a bin or
    # two around it at the wide scope's resolution (2.4 MS/s over 4096 bins
    # is 586 Hz a bin), so +-2 bins hides the line and nothing wider.
    DC_MASK_BINS = 2

    # Supplied by the app's subclass.
    STATE = None                 # ohscore.state.Registry
    CONFIG = None                # ohscore.config.Config
    DEVICES = None               # ohscore.devices.DeviceRegistry
    # decoders: the decoder sessions' results (ohscore/decoders.py), never in
    # anyone's default set.
    FEED_KINDS: tuple = ("wide", "zoom", "events", "meter", "state", "toast", "decoders")
    PRESETS: list = []           # built-in memories
    FREQ_KEY = "dl"              # what log records and memories call their frequency
    LOG_TITLE = ""               # first line of an ADIF export
    PROGRAM_ID = ""              # ADIF PROGRAMID
    APP_ID = ""                  # the store module id: logbook origin, controller pairing (shack-qo100nb)
    LOG_FREQ_FIELD = "freq_hz"   # the stored frequency FREQ_KEY shows (NB: the downlink, freq_rx_hz)
    THREAD_PREFIX = "ohscore"     # thread names: <prefix>-rx, -tx, -decode, -supervisor
    LOGGER = "ohscore.engine"
    # Status keys whose change re-derives the dials, segment and guard.
    DERIVE_ON: tuple = ("keyed",)
    # Controls that can move where a transmission lands: changing one while
    # keyed re-runs the transmit guard, and a refusal unkeys. An app adds
    # its own (HAM's repeater shift moves the transmit dial too).
    RECHECK_KEYED: tuple = ("vfo", "txVfo", "split", "xit", "xitOn", "mode", "txFilterLo", "txFilterHi", "cwPitch")
    # Modes send() takes whatever mode the radio is in: ones an app hears in
    # the background rather than as a mode on the rail, and sends from a
    # view of their own (NB: KG-STV, from its Beacon page). Such an over is
    # judged as what it is - its own mode's band-plan class and the signal
    # measured from its audio - by every check an over in the rail's mode
    # gets (_judged_mode), and keys exactly as any send() does. Without this
    # the guard judged it as the rail's mode: a KG-STV picture from USB was
    # "SSB" and refused in the digimode segment where it belongs.
    OVER_MODES: tuple = ()
    # What decides the licence in force (ohscore/countries.py in_force): a
    # change re-derives the `station` status, and while keyed re-checks.
    LICENCE_KEYS: tuple = ("callsign", "stationCountry", "licence", "licenceClass", "customLicence",
                           "stationConditions")
    # Modes whose decoder is built for one value of a further key, which
    # swaps the decoder when it changes as a mode change does: FreeDV's
    # waveform, HSmodem's speed (HSmodem does not detect a sender's speed;
    # both ends set the same one, as in DJ0ABR's program).
    DECODER_VARIANT: dict = {"freedv": "freedvMode", "hsmodem": "hsSpeed"}
    # Whether the CW decoder turns keying heard inside out over (shack_cw
    # Decoder stage 5): QO-100's F1A beacons need it. An app with no F1A
    # signals says False, so a fading beacon's dashes cannot turn the
    # next station inside out.
    CW_POLARITY: bool = True
    # Status logged on every change (ohscore/diag.py Watch), and status that
    # moves continuously and is logged at most every few seconds. An app
    # adds its own: NB its lock states and the IC-9700 link.
    DIAG_WATCH: tuple = ("running", "error", "keyed")
    DIAG_SLOW: tuple = ()
    # Counters in the device's and the audio backend's status that mean
    # samples were lost or late; the log gets a summary of their growth.
    DIAG_COUNTERS: tuple = ("overruns", "overflows", "late", "resyncs", "readerDrops", "underruns", "txUnderruns")
    STATUS_RING = 120            # status lines kept for a diagnostics report: two minutes at one a second
    # Who changed a setting, named in the line its save writes
    # (_log_saved): the module that called set(), as a person would say
    # it, plus its function - which for a dialog is the button or step.
    # Inferred from the caller rather than passed by each caller so the
    # dialogs need no change to say where a change came from; code that
    # knows better says so with `changes_from()`. Anything not listed is
    # named by module and function, which is still enough to find it.
    VIA_MODULES: dict = {"ohscore.ui.settings": "Settings dialog", "ohscore.ui.welcome": "welcome screen",
                         "ohsnb.ui.rigsetup": "IC-9700 setup assistant", "ohsnb.rigsetup": "IC-9700 setup assistant",
                         "ohscore.station": "station profile", "ohscore.server.app": "remote client"}
    # Who made a recording (its SigMF core:recorder): the app's name and the
    # package whose VERSION file says which release.
    APP_NAME = ""
    APP_PACKAGE = ""
    # IQ recording (ohscore/sigmf.py): status keys whose changes are marked
    # in a recording as annotations (`keyed` always is), and numeric ones
    # that move continuously and are tracked at most once a second.
    REC_STATES: tuple = ()
    REC_TRACK: tuple = ()
    # IQ playback (start_playback): settings the recording takes over while
    # it plays, given back when the radio returns and never saved meanwhile
    # (_save writes the operator's own values in their place). The core's
    # are the dial and mode a recording seeds; an app adds what it learns
    # from the signal (NB: rxCorr and what follows from it).
    PLAY_KEYS: tuple = ("vfo", "mode")

    def __init__(self, cfg: dict | None = None, *, conf_path: Path | None = None, data_dir: Path | None = None,
                 audio=None, device=None, persist: bool = True):
        self.log = logging.getLogger(self.LOGGER)
        spec = self.STATE.spec
        notes: list[str] = []
        self.conf_path = conf_path
        self.cfg = self.CONFIG.clean(cfg, notes) if cfg is not None else self.CONFIG.load(conf_path, notes)
        if cfg is None:
            self._log_loaded(conf_path)
        # Why the radio is not simply the one Settings chose (config.DEVICE_WHY):
        # read from what was handed in, which the cleaning above has dropped,
        # or from the file just loaded, whose copy must not stay in self.cfg.
        self.device_why = (cfg or {}).get(DEVICE_WHY) or self.cfg.pop(DEVICE_WHY, None)
        # config.RECEIVE_ONLY, read from what was handed in (cleaning drops it)
        # and kept for the whole run: start() applies it to every device.
        self.receive_only = bool((cfg or {}).get(RECEIVE_ONLY))
        if cfg is not None:
            # Non-persisted settings (simRealtime) are still honoured when passed in.
            for k, v in cfg.items():
                if k in spec and not spec[k]["persist"] and spec[k]["kind"] != "status":
                    try:
                        self.cfg[k] = self.STATE.coerce(k, v)
                    except ValueError as e:
                        notes.append(str(e))
        self.persist = persist
        self.data_dir = Path(data_dir) if data_dir else self.CONFIG.data_dir()
        self.st = self.STATE.defaults()
        for k in spec:
            if k in self.cfg:
                self.st[k] = self.cfg[k]
        self.st["keyed"] = False
        # On a controller, whether it can lend this app host libraries at
        # all (ohscore/hostlibs.py), and which are installed: looked at again
        # with the codecs (Decoders.codecs), since an administrator may
        # install one into the mounted folder while the app runs.
        self.st["hostLibs"] = hostlibs.status()
        self.keyer = Keyer(self, host.keyer_dir(self.data_dir))
        self.mem = Memories(self.PRESETS, self.cfg.get("memories", []), self.STATE.coerce, freq_key=self.FREQ_KEY)
        # The station's shared logbook and profile (ohscore/station.py): one
        # store per user per machine, or one inside the data folder an
        # engine was given (tests, --data), so a test never shares a log.
        self._station = None
        self._station_dir = Path(data_dir) if data_dir else None
        self._station_link = None
        self.logbook = Logbook(self.data_dir, freq_key=self.FREQ_KEY, adif_fields=self._adif_fields,
                               title=self.LOG_TITLE, program_id=self.PROGRAM_ID, station=lambda: self.station,
                               freq_field=self.LOG_FREQ_FIELD,
                               identity=lambda: (self.cfg.get("callsign", ""), self.cfg.get("locator", "")))
        # The profile follows the settings and back only for the program
        # an operator runs (persist): a test's throw-away engine must not
        # start a watch thread per radio it builds.
        if persist:
            try:
                self.station_link.adopt()
            except Exception:  # noqa: BLE001  a damaged store must not stop the radio
                logging.getLogger(self.LOGGER).warning("station profile not adopted", exc_info=True)
        self.lock = threading.RLock()
        self.feeds: dict[str, list[Feed]] = {k: [] for k in self.FEED_KINDS}
        # Decoder sessions (ohscore/decoders.py): the host is made by start().
        # The codec loader learns this app's folders first, before anything
        # (FreeDV's look for codec2) can ask it a question.
        sdr.configure(self.CONFIG.app.name, self.data_dir,
                      data_from_env=bool(data_dir) or bool(self.CONFIG.app.getenv("DATA")))
        self.decoders = Decoders(self)
        self._inj_audio, self._inj_device = audio, device
        if audio is not None:
            # Before start(): the store's server announces this backend's
            # format to a listener who connects while the radio is off.
            audio.set_out_rate(self.OUT_RATE)
        # A block of receive audio better than AUDIO_RATE, set by an app's
        # _demodulate for this block only (Radio's wide FM): at OUT_RATE,
        # mono (n,) or stereo (n, 2). Cleared before every block.
        self.heard_hi = None
        self.out_up = self.speech_up = None
        self.dev = None
        self.audio = None
        self.threads: list[threading.Thread] = []
        self.running = False
        self.stop_ev = threading.Event()
        self.pending: dict = {}
        # Unsaved operator state is written by its own saver thread
        # (_saver_loop), debounced: SAVE_QUIET_S after the last change of a
        # burst, and never more than SAVE_LONGEST_S after its first.
        # Before 23/10/2026 the supervisor wrote it on its next pass (0.1 s),
        # which had two holes: the supervisor runs only while the radio
        # does, and stop() saved only a running radio, so a dial moved while
        # the radio was stopped, failing to open or waiting for the broker
        # was never written at all; and a supervisor that died left every
        # later change for a stop() that a SIGKILL after podman's grace
        # period never reached. ohs-box came back on 145.500 after the
        # 0.1.22-beta.3 update with the dial on 145.650. The debounce is
        # also what spares an SD card a write per dial step.
        self.save_cv = threading.Condition()
        self.saver_thread: threading.Thread | None = None
        self.save_due = 0.0
        self.dirty_since = 0.0
        self.dirty = False
        # Set for state the engine corrects continuously by itself (NB's lock
        # corrections): saved too, but at most every 30 s (see _save).
        self.dirty_locks = False
        self.last_save = 0.0
        # Two threads save: the supervisor (every pass) and whoever calls
        # stop() or _save() directly. Each takes its snapshot under
        # self.lock but writes outside it, so a slower writer holding an
        # older snapshot could land last and put an operator's change back
        # as it was - with dirty already cleared, it stayed that way on
        # disk until the next change. And a forced save that found nothing
        # dirty returned while the supervisor was still writing the change
        # it had just taken, so the file read straight after it was the old
        # one (test_playback's filterHi, red under a loaded nightly run).
        # Snapshots are numbered and a write is dropped if a newer one has
        # already been written; save_lock covers only that check and the
        # write, and is never held while taking self.lock, so it adds no
        # lock-ordering hazard.
        self.save_seq = 0
        self.saved_seq = 0
        self.save_lock = threading.Lock()
        self.last_heartbeat = time.monotonic()
        self.reconf = True
        self.tx_thread: threading.Thread | None = None
        self.tx_req: dict | None = None
        self.tx_end = ""                         # how the current over ended, for its log line (_unkey)
        # The over in progress: tx_halt is set by every emergency unkey
        # (_unkey) and tells the TX thread to skip the drain; tx_releasing
        # is a normal end asked for (PTT released) once RF is up; tx_on_air
        # says it is - before that, a release has nothing to drain.
        self.tx_halt = threading.Event()
        self.tx_releasing = False
        self.tx_on_air = False
        self.tx_queue: deque = deque()
        # The standing transmit warnings (tx_warn).
        self.tx_warnings: dict[str, tuple] = {}     # key -> (rank, priority, seq, level, text, detail)
        self.tx_warn_seq = 0
        # An inverting converter (ohscore/converters.py: a high-side LO)
        # mirrors the spectrum between the radio and the air. The app sets
        # these when one is in use; the IQ is conjugated as it leaves the
        # device and before it is written, and nothing else in the engine
        # ever sees the mirrored spectrum - scopes, channels, demodulators,
        # modulators and locks all work in on-air terms, the device in the
        # radio's (docs/ham/DESIGN-HAM.md section 3: "flipped before it
        # reaches a feed, so the UI never knows"). rx_invert is read on the
        # receive thread only, tx_invert on the transmit thread only.
        self.rx_invert = False
        self.tx_invert = False
        self.decode_q: queue.Queue = queue.Queue(maxsize=64)
        self.decoder = None
        # PSKReporter uploads (ohscore/pskreporter.py), made by the first
        # decode heard with spotting on; it outlives stop()/start(), so a
        # settings restart neither loses nor resends the batch.
        self.spotter: pskreporter.Spotter | None = None
        self.decoder_mode = None
        # Decoders replaced (a mode change) or dropped (stop), waiting to be
        # closed. Closing is left to the decode thread, between two feeds:
        # it may be inside the old decoder's feed() at the moment of the
        # swap, and FreeDV's close() frees the codec2 handle that feed() is
        # using. Until NB 0.1.2 nothing closed them at all, which left every
        # FT8 decoder's working directory in the temp folder.
        self.retired: deque = deque()
        self.rx_gain_applied = None
        self.antenna_applied = None
        self.startup_notes = notes
        self.rx_samples = 0
        self.tx_t0 = 0.0
        self.last_mic_audio = 0.0
        self.mic_level = -120.0
        self.tx_peak = 0.0
        self.rx_level = -200.0
        self.monitor_due = 0.0
        self.meter_due = 0.0
        self.play_lock = threading.Lock()
        self.overruns = 0
        # Receive health, kept apart since 17/10/2026 (ohscore/rxprefetch.py):
        # `overruns` counts blocks of samples actually lost; `rx_late` the
        # blocks that took longer to process than they last - recoverable
        # while the prefetch queue holds them, and what `overruns` used to
        # count, which made every slow window action look like lost receive.
        self.rx_late = 0
        self.rx_lost = 0              # samples lost (prefetch queue + upstream)
        self.stream_hist: deque = deque()     # (monotonic, rx_samples, rx_lost) per tick, for rxStreamPct
        self.prefetch: rxprefetch.Prefetch | None = None
        self.watch = diag.Watch(self.log, self.DIAG_WATCH, self.DIAG_SLOW)
        self.status_lines: deque = deque(maxlen=self.STATUS_RING)
        self.next_status_line = 0.0
        self.saved_cfg: dict = dict(self.cfg)     # what the last save wrote, to name what the next changes
        self.change_via: dict[str, str] = {}      # key -> who last changed it, until the save that logs it
        self._via_local = threading.local()
        # The IQ recording in progress (read once per block by the receive
        # thread), and those ended whose writer has not finished yet: the
        # supervisor says when each is saved.
        self.rec: sigmf.Recorder | None = None
        self.rec_closing: list = []
        # The recording being played instead of the radio (a FileDevice,
        # chosen by start() over the configured device), and the operator's
        # own values of PLAY_KEYS from before it began.
        self.play = None
        self.play_saved: dict | None = None
        # The decoder session holding the receiver (hold_receiver), or None
        # while the operator has it: {session, by, block, centre, prior}.
        self.held: dict | None = None
        self._hold_tls = threading.local()
        # The receive IQ's DC blocker while _dc_block_wanted (made and
        # dropped by _configure_rx on the receive thread).
        self.dcblock: DcBlocker | None = None
        # Called with a word for what happened whenever a person (or a
        # client) does something with the radio: a set() that changes
        # something, a listener arriving, a key-up, a recording... (Radio's
        # band scanner keeps "idle" with it; client_activity).
        self.activity_hooks: list = []
        self.play_said_end = False
        # An auto-tune or best-audio request listening to the receive
        # channel (auto_tune, best_audio): set on the caller's thread,
        # filled on the receive thread, cleared by its analysis thread.
        # Whoever clears it first (the analysis with its result, the
        # receive thread when the dial moves) reports; _listen_claim.
        self.listening: dict | None = None
        self._listen_lock = threading.Lock()
        # Where an unsure auto-tune thought the station might be, offered to
        # the operator rather than applied (_offer_guesses): the next press
        # tries them in turn instead of listening again.
        self.tune_guess: dict | None = None
        # The last RECENT_SECONDS of the analysis bank's frames in USB and
        # LSB, (geometry, deque of (X, starts)): what a right-click's
        # auto-tune looks back at (_carrier_near).
        self.recent: tuple | None = None

    # ------------------------------------------------------------------ feeds
    def subscribe(self, kind: str, maxlen: int = 64) -> Feed:
        if kind not in self.feeds:
            raise ValueError(_("Unknown feed {kind}; feeds are {feeds}").format(kind=repr(kind), feeds=", ".join(self.FEED_KINDS)))
        f = Feed(kind, maxlen)
        with self.lock:
            self.feeds[kind].append(f)
        return f

    def unsubscribe(self, feed: Feed) -> None:
        with self.lock:
            if feed in self.feeds.get(feed.kind, []):
                self.feeds[feed.kind].remove(feed)

    def _publish(self, kind: str, item) -> None:
        for f in list(self.feeds[kind]):
            f.put(item)

    def toast(self, text: str, level: str = "info") -> None:
        self.log.info("%s: %s", level, text)
        self._publish("toast", {"t": time.time(), "level": level, "text": text})

    # ------------------------------------------------------- transmit warnings
    # A condition about transmitting that lasts - our downlink over the
    # beacon, an estimate over the licence's limit, the band plan set to
    # warn - is one standing line on the transmit card (status txWarning),
    # not a toast. Up to 0.1.9 each was a toast: NB's beacon check toasted
    # on every TX-lock measurement, several a second, and HAM's toasted
    # again at every key-up, so they stacked over the scopes and the
    # newest pushed the others away. One line that changes in place and
    # goes when the condition does says the same thing without the noise.
    # Several at once: the most serious level shows, then the higher
    # `priority` (HAM: the licence's power over the band plan), then the
    # most recent. Events - a refusal at PTT, an emergency unkey, a
    # failure - stay toasts: they happen once, and the operator must
    # notice them wherever they are looking.
    TX_WARN_RANK = {"error": 3, "warn": 2, "info": 1}

    def tx_warn(self, key: str, text: str, level: str = "warn", priority: int = 0, detail: str = "") -> None:
        """Set (or change in place) the standing transmit warning `key`.
        `detail` is the card's tooltip for it."""
        with self.lock:
            old = self.tx_warnings.get(key)
            if old is not None and old[3:] == (level, text, detail) and old[1] == priority:
                return
            if old is None or old[3] != level:
                self.tx_warn_seq += 1
                seq = self.tx_warn_seq
            else:
                seq = old[2]            # the same warning reworded keeps its place
            self.tx_warnings[key] = (self.TX_WARN_RANK.get(level, 2), priority, seq, level, text, detail)
            if old is None:
                self.log.info("%s (standing): %s", level, text)
        self._tx_warning_show()

    def tx_clear(self, *keys: str) -> None:
        """The conditions `keys` have cleared (unknown keys are ignored)."""
        with self.lock:
            gone = [k for k in keys if self.tx_warnings.pop(k, None) is not None]
        if gone:
            self._tx_warning_show()

    def _tx_warning_show(self) -> None:
        with self.lock:
            if self.tx_warnings:
                key, (_, _, _, level, text, detail) = max(self.tx_warnings.items(), key=lambda kv: kv[1][:3])
                w = {"key": key, "level": level, "text": text}
                if detail:
                    w["detail"] = detail
            else:
                w = {}
            self._status(txWarning=w)

    # ------------------------------------------------------------------ state
    def state(self) -> dict:
        with self.lock:
            s = dict(self.st)
        s["deviceStatus"] = dict(s.get("deviceStatus") or {})
        return s

    def _status(self, **kv) -> None:
        """Engine-side status changes, batched into the state feed by the supervisor."""
        with self.lock:
            for k, v in kv.items():
                if self.st.get(k) != v:
                    self.st[k] = v
                    self.pending[k] = v

    def _keep_setting(self, key: str, value) -> None:
        """A setting the engine itself changes (the decoder sessions it
        runs), validated, published and saved like an operator's change,
        without set()'s restart and authorisation rules: it is the record
        of what is running, not a request to change it."""
        value = self.STATE.coerce(key, value)
        with self.lock:
            self.st[key] = value
            self.pending[key] = value
            self.cfg[key] = value
            self.dirty = True

    def set(self, authorise: bool = False, drop_sessions: bool = False, **changes) -> dict:
        """Validate and apply. All-or-nothing: one bad value and nothing
        changes. Raises ValueError with a sentence for the operator. Never
        keys the transmitter (safety rule 1). A dial the background decoder
        sessions' span cannot hold raises SpanPinned, unless
        `drop_sessions`, which stops them first (the operator said yes)."""
        spec_of = self.STATE.spec
        clean = {}
        for k, v in changes.items():
            spec = spec_of.get(k)
            if spec is None:
                raise ValueError(_("There is no setting called {key}").format(key=repr(k)))
            if spec["kind"] == "status":
                raise ValueError(_("{key} is measured by the radio and cannot be set").format(key=k))
            if spec["auth"] and not authorise:
                raise ValueError(_("{key} can only be changed from Settings").format(key=k))
            clean[k] = self.STATE.coerce(k, v)
        holder = getattr(self._hold_tls, "on", False)
        if not holder and any(clean[k] != self.st.get(k) for k in clean):
            # A person's change (the holder's own and a restore are not):
            # a hold that gives way (a band scan) gives way to it first,
            # and puts back what it moved before this change applies.
            self.client_activity("set")
        held = self.held
        if held is not None and not holder:
            moved = [k for k in self.HELD_KEYS if k in clean and clean[k] != self.st.get(k)]
            if moved:
                raise ReceiverHeld(self._held_why(held, "tune"))
        if not holder:
            self._pin_check(clean, drop_sessions)
        with self.lock:
            self._adjust_set(clean)
            merged = dict(self.st)
            merged.update(clean)
            self.STATE.check_combined(merged)
            restart = [k for k in clean if spec_of[k]["restart"] and self.running and merged[k] != self.st[k]]
            changed = {k: v for k, v in clean.items() if self.st.get(k) != v}
            self.st.update(clean)
            for k, v in clean.items():
                if spec_of[k]["persist"]:
                    self.cfg[k] = v
            if changed:
                self.dirty = True
                self.reconf = True
            if "device" in changed:
                # Chosen now, in Settings: no longer a fallback or a
                # command-line override, whatever it was at start.
                self.device_why = None
        if changed:
            self._note_via(changed)
            self._derive()
            self._publish("state", {"t": time.time(), "changes": changed})
        if restart:
            self.toast(_("{settings}: takes effect when the radio restarts").format(settings=", ".join(restart)), "info")
        self._after_set(changed)
        if changed and self.persist:
            try:
                self.station_link.push(changed)
            except Exception:  # noqa: BLE001  the profile is a copy; the setting is already applied
                logging.getLogger(self.LOGGER).warning("station profile not updated", exc_info=True)
        if changed.get("pskReporter") is False and self.spotter is not None:
            self.spotter.clear()         # off means off: the waiting batch is not sent
        if "playLoop" in changed and self.play is not None:
            self.play.loop = self.st["playLoop"]
        if any(k in changed for k in self.KEYER_CANCEL) or ("keyerRepeat" in changed and not changed["keyerRepeat"]):
            self._keyer_cancel("repeat off" if "keyerRepeat" in changed else "retuned")
        req = self.tx_req
        if self.st["keyed"] and "mode" in changed and req and req.get("mode") in self.OVER_MODES:
            # The rail's mode is not the over's, so the guard below would let
            # it run on; but a mode change means the operator has moved on,
            # as it ends a CAT over (ohsnb/extrig.py) - and NB asks an IC-9700
            # for another mode on one, under a picture still going out.
            self._unkey(_("Unkeyed: the mode changed"), "warn", "mode changed")
        elif self.st["keyed"] and any(k in changed for k in self.RECHECK_KEYED + self.LICENCE_KEYS):
            why = self._tx_blocked(self._occupied_now(req), req)
            if why:
                self._unkey(f"Unkeyed: {why}", "warn", f"guard: {why}")
        return changed

    @property
    def station(self):
        """The shared store (shack_client Station), opened on first use."""
        if self._station is None:
            self._station = station_mod.open_station(self.APP_ID or "shack-desktop", self.app_version(),
                                                     self._station_dir)
        return self._station

    def release_station_thread(self) -> None:
        """A thread that used the store and is about to end gives its
        connection back (shack_client's Store.release_thread); nothing if
        the store was never opened, so a request that did not need it opens
        nothing. Since ohs-libs 326d251 the Store also sweeps up dead
        threads' connections by itself, which bounds the leak; this frees
        the connection at once rather than at the next sweep."""
        if self._station is not None:
            self._station.store.release_thread()

    @property
    def station_link(self) -> "station_mod.StationLink":
        if self._station_link is None:
            self._station_link = station_mod.StationLink(self.station, self)
        return self._station_link

    def app_version(self) -> str:
        """The app's VERSION file (ohsnb/VERSION, ohsradio/VERSION), '' if none."""
        try:
            mod = __import__(type(self).__module__.split(".")[0])
            return (Path(mod.__file__).resolve().parent / "VERSION").read_text().strip()
        except (OSError, AttributeError, ImportError):
            return ""

    def _adjust_set(self, clean: dict) -> None:
        """Called under the lock with the validated changes, before the
        cross-key rules run: the app may add consequential changes."""

    def _after_set(self, changed: dict) -> None:
        """Called once changes are applied and published, before the
        keyed re-check."""

    def licence_in_force(self) -> countries.InForce:
        """The station's country and the licence the guard applies, worked
        out again only when one of LICENCE_KEYS has changed: a cty.dat
        lookup per dial step would be waste."""
        s = self.st
        key = repr([s.get(k) for k in self.LICENCE_KEYS])
        if getattr(self, "_in_force_key", None) != key:
            self._in_force = countries.in_force(s, self.data_dir)
            self._in_force_key = key
        return self._in_force

    def _station_status(self) -> dict:
        """The `station` status; an app adds its own notes (NB: QO-100's
        footprint)."""
        return self.licence_in_force().info()

    def _derive(self):
        """Status that follows directly from settings (dials, segment, guard)."""
        with self.lock:
            s = self.st
            rx = self._rx_dial(s)
            txd = self._tx_dial(s)
            extra = self._derived(rx, txd)
            extra.setdefault("station", self._station_status())
            f_lo, f_hi = self._rx_passband(s)
        self._status(rxDial=rx, txDial=txd, rxFilterLo=f_lo, rxFilterHi=f_hi, **extra,
                     txBlocked=self._tx_blocked(None) if not self.st["keyed"] else self.st["txBlocked"])

    def _rx_passband(self, s: dict) -> tuple[float, float]:
        """The receive passband in Hz from the dial, as the demodulator in
        the current mode uses it (rxFilterLo/rxFilterHi): the one function
        the scopes and the demodulator already share."""
        return passband(s["mode"], s["filterLo"], s["filterHi"], s["cwPitch"], s["cwWidth"], s["amWidth"])

    def _rx_dial(self, s: dict) -> float:
        """The frequency the receiver demodulates: vfo + RIT."""
        return s["vfo"] + (s["rit"] if s["ritOn"] else 0.0)

    def _tx_dial(self, s: dict) -> float:
        """The frequency a transmission is meant to land on: txVfo when
        split, else vfo, + XIT."""
        return (s["txVfo"] if s["split"] else s["vfo"]) + (s["xit"] if s["xitOn"] else 0.0)

    def _derived(self, rx_dial: float, tx_dial: float) -> dict:
        """Further status that follows from the dials (called under the
        lock), such as the bandplan `segment`."""
        return {}

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self.running:
            return
        self.stop_ev.clear()
        self.st["keyed"] = False
        self.dev = self.play or self._inj_device or self.DEVICES.make(self.cfg)
        if self.receive_only and self.dev.can_tx:
            # On the instance, before open(): the device then opens exactly
            # as it does for any run (a Pluto's open() leaves its transmitter
            # at full attenuation with the TX LO powered down, and only
            # tx_start() undoes that), and every over is refused by the
            # check in _tx_blocked that a receive-only device already meets
            # - one path, not a second guard to keep in step. A device that
            # cannot transmit anyway (a recording) keeps its own reason.
            self.dev.can_tx = False
            self.dev.tx_refusal = RECEIVE_ONLY_REFUSAL
        try:
            self.dev.open()
        except (DeviceError, OSError, ImportError) as e:
            msg = f"Could not open the {self.cfg['device']} device: {e}"
            self._status(running=False, error=msg)
            self.toast(msg, "error")
            self.log.error("%s", msg)
            raise DeviceError(msg) from e
        self._log_device_open()
        realtime = bool(self.cfg.get("simRealtime", True)) if self.cfg["device"] == "sim" else True
        if self.play is not None:
            realtime = self.play.realtime
            self.play.set_rx_converter(self._play_converter())
        if self._inj_audio is not None:
            self.audio = self._inj_audio
            self.audio.set_out_rate(self.OUT_RATE)
            self.audio.start()
            note = ""
        else:
            self.audio, note = audio_mod.make_backend(self.cfg, realtime=realtime, out_rate=self.OUT_RATE)
        # 12 kHz receive audio to OUT_RATE (a whole multiple of it): the
        # FFT interpolator the Pluto's transmit path uses (dsp/multirate.py),
        # flat to 5 kHz and 90 dB down past 7. The sound card path's
        # polyphase Resampler did 12 -> 48 kHz on the desktop before
        # 23/10/2026 and cost eight times as much here (1.0 % of a 6900HX
        # core against 0.12); with the card at 48 kHz it now does nothing.
        # One for the receive thread and one for FreeDV's speech, which
        # arrives on the decode thread.
        self.out_up = self.speech_up = None
        if self.OUT_RATE != AUDIO_RATE:
            m = self.OUT_RATE // AUDIO_RATE
            if m * AUDIO_RATE != self.OUT_RATE:
                raise DeviceError(f"OUT_RATE {self.OUT_RATE} is not a whole multiple of {AUDIO_RATE}")
            self.out_up, self.speech_up = Interpolator(m), Interpolator(m)
        if note:
            self.toast(note, "warn")
        self.log.info("audio: %s", self.audio.status() if self.audio else "none")
        for n in self.startup_notes:
            self.toast(n, "warn")
        fs = self.dev.fs
        self.geo = Geometry(fs)
        self.analysis = Analysis(self.geo)
        self.vfo_ch = Channel(self.geo, self.geo.decimation_for(AUDIO_RATE))
        if abs(self.vfo_ch.rate - AUDIO_RATE) > 1e-6:
            raise DeviceError(f"Sample rate {fs} does not decimate to 12 kHz")
        self.zoom_ch = None
        self.zoom_scope = None
        self.wide = None
        self.demod = Demod()
        self.nb = NoiseBlanker()
        self.nr = NoiseReduction()
        self._start_consumers()
        self.mod = SsbMod()
        self.synth = Synthesis(self.geo)
        self.tx_src = Source(self.geo, self.geo.decimation_for(AUDIO_RATE))
        self.rx_if = self._initial_tuning()
        try:
            self.dev.set_rx_if(self.rx_if)
        except DeviceError as e:
            # A device that cannot tune where the app starts (a recording of
            # somewhere else): closed again, so a failed start holds nothing.
            self.dev.close()
            if self.audio:
                self.audio.stop()
            self._status(running=False, error=str(e))
            raise
        self.rx_gain_applied = self._rx_gain_wanted(self.st)     # open() applied the configured gain
        self.antenna_applied = str(self.st.get("soapyAntenna", "") or "")   # open() applied this antenna too
        self.rx_samples = 0
        self.modes_info = self._mode_caps(modes_glue.available(self.STATE.modes, self.st["freedvMode"]))
        self.decoders.open(realtime)
        self.running = True
        self.last_heartbeat = time.monotonic()
        self._status(running=True, error="", canTx=bool(self.dev.can_tx), fs=fs, modes=self.modes_info,
                     **self._sim_status(), **self._start_status())
        if self.st["simFallback"]:
            self.toast(self.st["simWhy"], "warn")
        self._derive()
        self.watch.seed(dict(self.st))
        self.reconf = True
        self.decoders.restore()
        self.decoders.scan_codecs_later()
        for name, fn in (("rx", self._rx_loop), ("decode", self._decode_loop), ("supervisor", self._supervise)):
            t = threading.Thread(target=fn, name=f"{self.THREAD_PREFIX}-{name}", daemon=True)
            self.threads.append(t)
            t.start()

    def _log_device_open(self) -> None:
        """Once per open: what was opened, at what rate, and anything the
        driver had to work around (a refused FIR); and, for a radio that
        has them, its IIO context attributes (firmware, model, serial)."""
        try:
            st = self.dev.status()
        except Exception as e:  # noqa: BLE001 - a status that fails must not stop the open
            st = {"status": f"unavailable ({e})"}
        keep = {k: v for k, v in st.items() if not isinstance(v, (dict, list)) or k == "notes"}
        self.log.info("device %s opened: %s", self.cfg.get("device"), keep)
        ctx = self.device_context()
        if ctx:
            self.log.info("device context: %s", ctx)

    def device_context(self) -> dict:
        """The open radio's IIO context attributes (firmware version,
        model, serial...), read from the context the device already holds:
        {} for a device without one, or when none is open. Never opens a
        radio - a report asking for this must not grab hardware another
        program may hold."""
        dev = self.dev
        fn = getattr(dev, "context_attrs", None) if dev is not None else None
        if fn is None:
            return {}
        try:
            return dict(fn())
        except Exception:  # noqa: BLE001 - a context gone stale mid-read
            return {}

    def _sim_status(self) -> dict:
        """simWhy and simFallback for the device just opened. Asked of the
        device itself (its kind), not the `device` setting: a recording
        played back opens no simulator whatever the setting says. The
        sentence is the engine's, not the window's, so a headless run and
        a diagnostics report say the same thing the badge does."""
        if getattr(self.dev, "kind", "") != "sim":
            return {"simWhy": "", "simFallback": False}
        why = self.device_why or {}
        if why.get("fallback"):
            return {"simWhy": f"The simulator is standing in for your radio because {why['why']}. "
                              f"Choose your radio again in Settings › Radio.", "simFallback": True}
        if why.get("why"):
            return {"simWhy": f"The simulator was chosen {why['why']}.", "simFallback": False}
        return {"simWhy": "Settings › Radio is set to the simulator (the default until you choose a radio).",
                "simFallback": False}

    def _start_consumers(self) -> None:
        """Create the app's own receive consumers (the geometry exists)."""

    def _mode_caps(self, info: dict) -> dict:
        """What each mode can do here ({mode: {decode, encode, missing}}),
        given what the core found; an app corrects it for modes it runs itself."""
        return info

    def _initial_tuning(self) -> float:
        """Where the receiver is first tuned, in the device's terms."""
        raise NotImplementedError

    def _start_status(self) -> dict:
        """Status published with running=True."""
        return {}

    def stop(self) -> None:
        if not self.running:
            # Changes made while stopped (or while the radio would not open)
            # have no supervisor to write them: written here, on the way out.
            self._save(force=True)
            return
        # A hold that gives way puts the operator's settings back while the
        # radio still runs, so the saves below write theirs.
        self.preempt_receiver("stop")
        # Saved before the teardown, which can take seconds (threads joined,
        # the device closed): a container stop gives SIGTERM a grace period
        # and then kills, and the dial must be on disk by then. Saved again
        # at the end for anything the teardown itself changes.
        self._save(force=True)
        self.keyer.shutdown()
        self.tx_clear("keyer")
        self._unkey("", None, "radio stopped")
        if self.tx_thread:
            self.tx_thread.join(timeout=2)
        rec = self.rec
        if rec is not None:
            self._rec_end(rec, "the radio stopped")
        self.running = False
        self.stop_ev.set()
        self.recent = None
        if self.listening is not None:
            self.listening = None
            self._status(autoBusy="")
        try:
            self.decode_q.put_nowait(None)
        except queue.Full:
            pass
        pf = self.prefetch
        if pf is not None:
            # The reader is stopped before the device closes, so a close
            # never lands in the middle of its read (one block at most).
            pf.stop()
            pf.thread.join(timeout=1.0)
        # The decoder host before the device (RADIO-SDR-PLAN §3.5): it holds
        # no hardware, so this never delays the broker's release, and its
        # workers join within a second.
        self.decoders.close()
        if self.dev:
            try:
                self.dev.close()
                self.log.info("device %s closed", self.cfg.get("device"))
            except Exception:  # noqa: BLE001
                self.log.warning("closing the %s device failed", self.cfg.get("device"), exc_info=True)
        for t in self.threads:
            t.join(timeout=3)
        self.prefetch = None
        decoding = any(t.is_alive() for t in self.threads)
        self.threads = []
        # The next start() makes a fresh decoder (decoder_mode None), so this
        # one can be closed - by this thread, now the decode thread is gone.
        if self.decoder is not None:
            self.retired.append(self.decoder)
        self.decoder, self.decoder_mode = None, None
        if not decoding:
            self._close_retired()
        if self.audio:
            self.audio.stop()
        # A recording's last blocks and its final metadata are on the
        # writer thread: waited for, so quitting never leaves a recording
        # without the .sigmf-meta that makes it readable.
        for r in list(self.rec_closing):
            r.wait(5.0)
        self._rec_tick()
        self._status(running=False, simWhy="", simFallback=False)
        self._save(force=True)

    def radiates(self) -> bool:
        """Whether keying now would put RF anywhere: asked of the device the
        engine holds (the one a restart has just made, even before it has
        opened), never of the `device` setting, which can name a radio the
        engine has not switched to yet. True when there is no device."""
        return self.dev is None or bool(getattr(self.dev, "radiates", True))

    def heartbeat(self) -> None:
        self.last_heartbeat = time.monotonic()

    # How soon unsaved operator state reaches the disk (see __init__).
    SAVE_QUIET_S = 1.0
    SAVE_LONGEST_S = 3.0

    @property
    def dirty(self) -> bool:
        """Operator state not yet on disk. A property so every place that
        marks it - the engine's, Radio's and NB's alike - also schedules
        the debounced save, without each having to remember to."""
        return self._dirty

    @dirty.setter
    def dirty(self, value: bool) -> None:
        if not value:
            self._dirty = False
            return
        now = time.monotonic()
        if not getattr(self, "_dirty", False):
            self.dirty_since = now
        self._dirty = True
        self.save_due = min(now + self.SAVE_QUIET_S, self.dirty_since + self.SAVE_LONGEST_S)
        if self.persist:
            self._saver_wake()

    def _saver_wake(self) -> None:
        # Callers usually hold self.lock; save_cv is never held while taking
        # self.lock (the saver drops it before _save), so no ordering hazard.
        with self.save_cv:
            self.save_cv.notify()
            if self.saver_thread is None:
                self.saver_thread = threading.Thread(target=self._saver_loop, name=f"{self.THREAD_PREFIX}-saver",
                                                     daemon=True)
                self.saver_thread.start()

    def _saver_loop(self) -> None:
        """Writes unsaved state once it is due, running or not; ends when
        nothing is left unsaved, and the next change starts it again (an
        engine that is idle, or a test's, keeps no thread)."""
        while True:
            with self.save_cv:
                if not self.dirty:
                    self.saver_thread = None
                    return
                wait = self.save_due - time.monotonic()
                if wait > 0:
                    self.save_cv.wait(wait)
                    continue
            try:
                self._save()
            except Exception:  # noqa: BLE001 - a failed save is toasted in _save; the thread must live on
                self.log.warning("saving settings failed", exc_info=True)
                with self.save_cv:
                    self.saver_thread = None
                return

    def save_now(self) -> None:
        """Write unsaved state now, waiting for a write already under way:
        for a shutdown, before anything slow can delay it past the
        process's grace period."""
        self._save(force=True)

    def _save(self, force: bool = False):
        if not self.persist:
            return
        with self.lock:
            idle = not (self.dirty or self.dirty_locks)
            # Lock corrections change every half second; writing them that
            # often would wear an SD card for nothing. Operator changes go out
            # once they are due (SAVE_QUIET_S/SAVE_LONGEST_S), lock-only
            # changes every 30 s.
            now = time.monotonic()
            if not idle and not force and self.dirty and now < self.save_due:
                return
            if not idle and not force and not self.dirty and now - self.last_save < 30:
                return
            if not idle:
                cfg = dict(self.cfg)
                self._save_extra(cfg)
                if self.play_saved is not None:
                    # Playing: what the recording set is not the operator's.
                    spec = self.STATE.spec
                    cfg.update({k: v for k, v in self.play_saved.items() if spec[k]["persist"]})
                held = self.held
                if held is not None:
                    # Held (DAB, a band scan): the dial on disk stays the
                    # operator's, so a crash meanwhile does not leave the
                    # radio on Band III at the next start.
                    spec = self.STATE.spec
                    cfg.update({k: v for k, v in held["prior"].items() if spec[k]["persist"]})
                cfg["memories"] = list(self.mem.user)
                self.dirty = self.dirty_locks = False
                self.last_save = now
                self.save_seq += 1
                seq = self.save_seq
        if idle:
            if force:
                # Nothing new, but the supervisor may have taken the last
                # change a moment ago and still be fsyncing it: a forced
                # save (stop(), a test about to read the file) means "on
                # disk when this returns", so wait for that write.
                with self.save_lock:
                    pass
            return
        with self.save_lock:
            if seq < self.saved_seq:
                return               # a newer snapshot is already on disk
            try:
                self.CONFIG.save(cfg, self.conf_path)
                err = None
            except OSError as e:
                err = e
            else:
                self.saved_seq = seq
        # Outside save_lock: the toast and the log are not the write, and a
        # slow log handler should not hold up the other saving thread.
        if err is not None:
            self.toast(_("Could not save settings: {error}").format(error=err), "warn")
            return
        self._log_saved(cfg)

    # The engine's own corrections, saved every 30 s while locked: logged
    # as DEBUG, so the operator's changes are not buried under them.
    QUIET_SAVES = frozenset({"rxCorr", "txCorr", "txCorrTrusted", "rigTxCorr", "rigTxCorrTrusted"})

    def _log_saved(self, cfg: dict) -> None:
        """One line per key a save changed: old -> new and who changed it.
        Until 12/10/2026 this named the keys only, never values, because
        the log goes out in a report; but "rigTxAudioOut changed" could not
        say what Ray's sound device had been or become, which was the whole
        question. Values now go in, through diag.setting_value, which
        redacts anything secret-looking and shortens long ones; the
        callsign and locator a report already carries."""
        prev, self.saved_cfg = self.saved_cfg, cfg
        changed = sorted(k for k in set(cfg) | set(prev) if cfg.get(k) != prev.get(k))
        for k in changed:
            via = self.change_via.pop(k, "") or "engine"
            line = ("setting %s: %s -> %s (%s)", k, diag.setting_value(k, prev.get(k)),
                    diag.setting_value(k, cfg.get(k)), via)
            if k in self.QUIET_SAVES:
                self.log.debug(*line)
            else:
                self.log.info(*line)

    @contextlib.contextmanager
    def changes_from(self, via: str):
        """Name who is changing settings on this thread, for the save's log
        line, where the caller would be named less well (VIA_MODULES)."""
        prev = getattr(self._via_local, "via", None)
        self._via_local.via = via
        try:
            yield
        finally:
            self._via_local.via = prev

    def _note_via(self, changed: dict) -> None:
        via = getattr(self._via_local, "via", None)
        if not via:
            # The first caller outside the engine itself (recall() and
            # set_mode_tuned() call set() for their own callers).
            f = sys._getframe(2)
            while f is not None and f.f_globals.get("__name__") == __name__:
                f = f.f_back
            if f is None:
                via = "engine"
            else:
                mod = f.f_globals.get("__name__", "?")
                label = self.VIA_MODULES.get(mod)
                via = f"{label} ({f.f_code.co_name})" if label else f"{mod}.{f.f_code.co_name}"
        for k in changed:
            self.change_via[k] = via

    def _log_loaded(self, conf_path: Path | None) -> None:
        """What loading the settings file changed in it: a migration (a
        renamed key, a converter made from old settings) or a repair (a
        value out of range put back). Logged here because the first save
        then writes it without a word: saved_cfg starts from what was
        loaded. Keys the file did not have are new defaults, not changes,
        and are left out."""
        path = conf_path or self.CONFIG.conf_path()
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for k in sorted(raw):
            if k in ("memories", getattr(self.CONFIG, "VERSION_KEY", None)):
                continue
            if k not in self.cfg:
                self.log.info("setting %s: %s -> (removed) (startup migration)", k, diag.setting_value(k, raw[k]))
            elif raw[k] != self.cfg[k]:
                self.log.info("setting %s: %s -> %s (startup migration)", k, diag.setting_value(k, raw[k]),
                              diag.setting_value(k, self.cfg[k]))

    def _save_extra(self, cfg: dict) -> None:
        """Copy engine-maintained state into the config about to be saved."""

    # ------------------------------------------------------------- frequencies
    def _off(self, dial: float) -> float:
        """Offset from the IQ stream's DC of a dial frequency."""
        raise NotImplementedError

    def _dial_at(self, off: float) -> float:
        """The dial frequency at offset `off` from the IQ stream's DC (the
        inverse of _off)."""
        raise NotImplementedError

    def wide_span(self) -> tuple[float, float]:
        """The dial frequencies the wide scope covers."""
        raise NotImplementedError

    # ------------------------------------------------------------------ receive
    @staticmethod
    def _rx_gain_wanted(s: dict) -> tuple:
        """The front-end gain as the device takes it: the gain figure only
        matters while the mode is manual."""
        return (s["rxGainMode"], float(s["rxGain"]) if s["rxGainMode"] == "manual" else None)

    def _configure_rx(self):
        s = self.state()
        # The receiver gain is applied here, on the rx thread between two
        # reads, like every other receive reconfiguration. It used to reach
        # the device only when the device was next opened, so a change in
        # Settings did nothing until Radio > Restart the radio.
        # What is applied is what _rx_gain_wanted says, which an app may
        # override (NB's dish alignment holds the gain without touching the
        # operator's setting).
        want = self._rx_gain_wanted(s)
        if want != self.rx_gain_applied:
            self.rx_gain_applied = want
            try:
                self.dev.set_rx_gain(want[0], float(s["rxGain"]) if want[1] is None else float(want[1]))
            except DeviceError as e:
                self.toast(_("Receiver gain not applied: {error}").format(error=e), "warn")
        # The antenna input, the same way: set_antenna is called on the
        # open device with no reopen (soapy.py's SoapySDRPlay3 path takes
        # it on a running stream); a device with no antenna to pick
        # ignores it (Device.set_antenna's base no-op). An unknown input
        # is refused by the device and only toasted here, never applied:
        # api/set and the Settings dialog validate it first, but a label
        # saved for a radio that was later swapped for a different one
        # must not silently try its old antenna's name.
        want_ant = str(s.get("soapyAntenna", "") or "")
        if want_ant != self.antenna_applied:
            if s["keyed"]:
                # Every device with an antenna to switch is receive-only
                # (can_tx is False), so nothing here could be on the air -
                # but safety rule 2 is never trusted to a device's own
                # kind, so the switch waits for the next unkeyed
                # reconfigure instead of touching the open device mid-over.
                self.reconf = True
            else:
                self.antenna_applied = want_ant
                try:
                    self.dev.set_antenna(want_ant)
                except DeviceError as e:
                    self.toast(_("Antenna not changed: {error}").format(error=e), "warn")
        if self._dc_block_wanted():
            if self.dcblock is None or self.dcblock.fs != float(self.geo.fs):
                self.dcblock = DcBlocker(self.geo.fs)
        else:
            self.dcblock = None
        lo, hi = passband(s["mode"], s["filterLo"], s["filterHi"], s["cwPitch"], s["cwWidth"], s["amWidth"])
        self.demod.configure(s["mode"], lo, hi, s["agc"], s["rfGain"])
        self.nb.threshold = s["nbThreshold"]
        self.nr.configure(s["nr"], s["nrStrength"], s["mode"])
        w_lo, w_hi = self.wide_span()
        nw = wide_nfft(s["wideBins"], self.geo.fs, w_hi - w_lo)
        if self.wide is None or self.wide.nfft != nw or self.wide.avg != s["wideAvg"] or self.wide.fps != s["scopeFps"]:
            self.wide = Scope(self.geo.fs, nw, s["scopeFps"], s["wideAvg"])
        zspan = s["zoomSpanHz"]
        d = self.geo.decimation_for(zspan / 0.8)
        if self.zoom_ch is None or self.zoom_ch.d != d:
            self.zoom_ch = Channel(self.geo, d)
            self.zoom_scope = None
        nz = wide_nfft(s["zoomBins"], self.zoom_ch.rate, zspan)
        if (self.zoom_scope is None or self.zoom_scope.nfft != nz or self.zoom_scope.avg != s["zoomAvg"]
                or self.zoom_scope.fps != s["scopeFps"]):
            self.zoom_scope = Scope(self.zoom_ch.rate, nz, s["scopeFps"], s["zoomAvg"])
        self._configure_consumers(s)
        # The FreeDV waveform is part of what the decoder is, so changing it
        # while in FreeDV swaps the decoder just as a mode change does; so is
        # HSmodem's speed (a key only an app offering HSmodem has).
        variant = self.DECODER_VARIANT.get(s["mode"])
        want = (s["mode"], s.get(variant)) if variant else s["mode"]
        if want != self.decoder_mode:
            self._swap_decoder(s["mode"])
            self.decoder_mode = want
        # PSK's extra stations, live: the session keeps every channel that
        # stays in the list (modes/sdrmode.py PskDecoder.set_channels).
        follow = getattr(self.decoder, "set_channels", None)
        if follow is not None:
            follow(s.get("pskChannels") or [])

    def _dc_block_wanted(self) -> bool:
        """Whether the receive IQ goes through the DC blocker (the app's
        rule: Radio's dcBlock setting and its device); never here."""
        return False

    def _configure_consumers(self, s: dict) -> None:
        """Apply settings to the app's own receive consumers."""

    def _swap_decoder(self, mode: str):
        self.decoder_mode = mode
        dec = None
        if mode in self.STATE.digital or mode == "cw":
            opts = {"freq": self.st["cwPitch"], "polarity": self.CW_POLARITY} if mode == "cw" else {}
            if mode == "freedv":
                opts["audio_out"] = self._decoded_speech
            if mode == "sstv":
                # The decoder's default is the current directory - wherever the
                # program happened to be started from. Received pictures are the
                # operator's data and belong with the log.
                opts["out_dir"] = str(self.sstv_dir())
            if mode == "hsmodem":
                # Received files are the operator's, kept with the log, under
                # safe names (ohscore/modes/hsmodem.py safe_name).
                opts["folder"] = str(self.hsmodem_dir())
                opts["speed"] = int(self.st.get("hsSpeed") or 4410)
            if mode in ("ft8", "ft4", "q65", "js8"):
                opts["calls"] = self._slot_calls
            if mode in ("psk31", "psk63", "psk125"):
                opts["channels"] = list(self.st.get("pskChannels") or [])
            if modes_glue.hosted(mode):
                # A shack_sdr session in the engine's own host, listed as
                # the decoder session "vfo" (ohscore/decoders.py).
                opts["link"] = self.decoders.link()
            if mode in ("ft8", "ft4"):
                # Asked at every slot, like the calls, so Settings' choice
                # applies from the next slot; the decoder says which one it
                # used, including a fallback to jt9 after a failure.
                opts["decoder"] = lambda: self.st.get("ft8Decoder", "auto")
                opts["on_decoder"] = lambda name: self._status(ft8DecoderInUse=name)
            dec = modes_glue.decoder(mode, self._emit_event, freedv_mode=self.st["freedvMode"], **opts)
        if mode not in ("ft8", "ft4"):
            self._status(ft8DecoderInUse="")
        # A decoded mode with no decoder used to be silence: the store image
        # of 0.1.10-beta.1 had no FT8 decoder, FT8 could still be chosen,
        # and nothing anywhere said why no slot ever decoded. Now it is a
        # toast when the mode is chosen and a standing status line
        # (decoderMissing) for as long as it stays chosen, in the words the
        # mode registry already has for it.
        missing = ""
        if dec is None and (mode in self.STATE.digital or mode == "cw"):
            label, why = modes_glue.why_not(mode, self.st["freedvMode"])
            missing = why or _("its decoder did not start (the log says why)")
            self.toast(_("{mode} cannot be decoded here: {why}").format(mode=label, why=missing), "warn")
        self._status(decoderMissing=missing)
        old, self.decoder = self.decoder, dec
        if old is not None:
            retire = getattr(old, "retire", None)
            if retire is not None:
                retire()            # a decoder session (modes/sdrmode.py) ends with its mode
            self.retired.append(old)

    def _slot_calls(self) -> tuple[str, str]:
        """(MyCall, DxCall) for an FT8/FT4 decode, asked on the decode
        thread at each slot: the operator's call and the sequencer's DX call
        (jt9 -c/-x, as WSJT-X gives its decoder). Two reads of the state
        dict, each atomic; no lock needed for values only ever replaced."""
        return self.st.get("callsign", ""), self.st.get("dxCall", "")

    def _close_retired(self) -> None:
        """Close the decoders retired since last time (see `retired`)."""
        while self.retired:
            dec = self.retired.popleft()
            close = getattr(dec, "close", None)
            if close is None:
                continue
            try:
                close()
            except Exception as e:  # noqa: BLE001 - a decoder that will not close costs a temp folder, not receive
                self.log.warning("closing a %s decoder failed: %s", type(dec).__module__, e)

    def _decoded_speech(self, speech: np.ndarray):
        """FreeDV: the decoder's speech replaces the demodulated audio. Called
        on the decode thread, hence the lock around the playback resampler."""
        vol = 0.0 if self.st["mute"] else self.st["volume"]
        with self.play_lock:
            self.audio.play(self._to_out(np.asarray(speech, np.float32), self.speech_up) * np.float32(vol))

    def audio_channels(self) -> int:
        """How many channels the receive audio has now: 2 while the mode is
        making stereo (an app's `heard_hi`) or a held session's sound is
        stereo (DAB's), else 1. What a recording starting now records
        (ohscore/server/recording.py)."""
        if self.held is not None:
            return self.decoders.held_channels()
        return 1

    @staticmethod
    def _to_out(audio: np.ndarray, up) -> np.ndarray:
        """12 kHz audio at OUT_RATE, through the interpolator `up` (None:
        the app plays at 12 kHz)."""
        return audio if up is None else up(np.asarray(audio, np.complex64)).real.astype(np.float32)

    def _emit_event(self, ev: dict):
        ev = dict(ev)
        ev.setdefault("t", time.time())
        ev.setdefault("dial", self.st["rxDial"])
        self._with_country(ev)
        self._publish("events", ev)
        # Every decoder's events pass here, so this is the one place spots
        # are taken from; the spotter decides which events are spots. Off
        # (the default) it is never made: no socket, no thread.
        if self.st.get("pskReporter"):
            self._spotter().offer(ev, self.st.get("callsign", ""), self.st.get("locator", ""))

    def _with_country(self, ev: dict) -> None:
        """Name the sender's DXCC entity on a decode that names a sender:
        "country" (cty.dat's name, as the desktop's Country column shows
        it), "dxcc" (its primary prefix) and "continent". Added here, where
        every decoder's events pass, so each client of api/events - Remote
        on a tablet, a TV, a phone - shows the column without carrying its
        own country file (Brian, 12/10/2026: "show countries on it like we
        do in the linux/windows app"). The lookup is the desktop panel's
        own (ohscore/dxcc.py, the operator's cty.dat first), so the two
        never disagree. Nothing is added for a call cty.dat cannot place
        (/MM, a hashed <...>, free text): no field rather than a guess.
        No ISO country code or flag: cty.dat has none, and a hand-kept
        table of 340 entities would go stale with every new one."""
        call = ev.get("call")
        if not call or "country" in ev:
            return
        try:
            ent = dxcc.load(self.data_dir).lookup(str(call))
        except Exception as e:  # noqa: BLE001 - a bad country file costs a column, never a decode
            self.log.warning("country lookup for %s failed: %s", call, e)
            return
        if ent is not None:
            ev.update(country=ent.name, dxcc=ent.prefix, continent=ent.continent)

    def flush_spots(self, timeout: float = 2.0) -> None:
        """The program is closing: send the spots still waiting rather than
        lose up to five minutes of them, as WSJT-X does on exit. On a thread
        joined for at most `timeout`, so a dead network or a slow DNS
        lookup cannot hold the window open."""
        sp = self.spotter
        if sp is None or not self.st.get("pskReporter"):
            return
        t = threading.Thread(target=sp.flush, name=f"{self.THREAD_PREFIX}-spots", daemon=True)
        t.start()
        t.join(timeout)

    def _spotter(self) -> pskreporter.Spotter:
        if self.spotter is None:
            version = diag.app_version(self.APP_PACKAGE) if self.APP_PACKAGE else ""
            self.spotter = pskreporter.Spotter(f"{self.APP_NAME or self.CONFIG.app.name} {version}".strip())
        return self.spotter

    PREFETCH_S = 2.0   # seconds of receive the DSP may fall behind before the oldest is dropped (rxprefetch.py)

    def _rx_read(self, n: int):
        """The next block from the device: through the prefetch thread for
        a device that wants one (ohscore/rxprefetch.py), started here and
        again after a reconnect; directly otherwise. None: nothing yet, ask
        again (the stop flag is checked in between)."""
        if not getattr(self.dev, "rx_prefetch", False):
            return self.dev.read(n)
        pf = self.prefetch
        if pf is None:
            if self.stop_ev.is_set():
                return None               # stopping: no new reader on a device being closed
            pf = self.prefetch = rxprefetch.Prefetch(self.dev, n, self.geo.fs, depth_s=self.PREFETCH_S,
                                                     name=f"{self.THREAD_PREFIX}-rxread").start()
        try:
            return pf.read()
        except Exception:
            self.prefetch = None          # its thread has ended; the next read after the reconnect starts another
            raise

    def _rx_loop(self):
        n = self.BLOCK_HOPS * self.geo.L
        cpu = 0.0
        wait = 0.0
        while not self.stop_ev.is_set():
            try:
                x = self._rx_read(n)
            except Exception as e:  # noqa: BLE001 - any device failure: unkey, report, reconnect
                if self.stop_ev.is_set():
                    break
                self._device_lost(e)
                continue
            if x is None:
                continue
            pf = self.prefetch
            if pf is not None and pf.gap:
                # Samples lost before this block, upstream or in the queue:
                # an overrun, said with its length.
                self.overruns += 1
                self.rx_lost += pf.gap
            t0 = time.perf_counter()
            c0 = time.thread_time()
            try:
                self._rx_block(x)
            except Exception as e:  # noqa: BLE001 - a DSP bug must not kill receive silently
                self.log.exception("rx block failed")
                self._status(error=f"Receive processing failed: {e}")
            dt = time.perf_counter() - t0
            dc = time.thread_time() - c0
            block_s = len(x) / self.geo.fs
            # `cpu` used to be dt/block_s - wall-clock time, so it counted
            # time spent waiting for Python's GIL as if it were work done.
            # That hid a real stall on 07/10 (NB on the laptop, GUI thread
            # at 82%): "CPU 41%" while receive was actually starved most of
            # the block, because the GIL wait landed inside dt and nowhere
            # else. thread_time() is this thread's own CPU time, so dc/dt is
            # the genuine split; cpu is now dc/block_s (what this thread
            # actually used) and `wait` is the rest (dt-dc)/block_s - time
            # charged to the block that this thread did not get to run in.
            # Windows' thread_time() only ticks in ~15.6 ms steps (its
            # clock_gettime(CLOCK_THREAD_CPUTIME_ID) resolution), coarse
            # next to one ~75 ms block (BLOCK_HOPS docstring) - the existing
            # 0.9/0.1 smoothing (already here for `cpu`, now shared by
            # `wait`) is reused rather than added to just for this, and
            # already averages over about ten blocks, enough to smooth that
            # quantisation out on both platforms.
            cpu = 0.9 * cpu + 0.1 * dc / block_s
            wait = 0.9 * wait + 0.1 * max(0.0, dt - dc) / block_s
            self.cpu = cpu
            self.cpu_wait = wait
            # A block that took longer to process than it lasts. The first
            # second is left out, where numpy plans its FFTs. Behind the
            # prefetch queue it costs nothing but latency, and is counted
            # as late; read directly (a device without the queue), each one
            # is time the device's own buffers had to cover, and the best
            # sign of lost samples there is - so it stays an overrun there.
            if dt > block_s and self.rx_samples > self.geo.fs:
                self.rx_late += 1
                if pf is None:
                    self.overruns += 1

    def _device_lost(self, e: Exception):
        self.log.warning("device %s lost: %s", self.cfg.get("device"), e)
        diag.notable("radio-lost", f"{self.cfg.get('device')}: {e}")
        self._unkey(f"Unkeyed: the {self.cfg['device']} stopped responding ({e})", "error", "device lost")
        self._status(error=f"Device problem: {e}", running=False)
        while not self.stop_ev.wait(2.0):
            try:
                self.dev.close()
                self.dev.open()
                self.dev.set_rx_if(self.rx_if)
                self._status(error="", running=True)
                self.log.info("device %s reconnected", self.cfg.get("device"))
                self.toast(_("Device reconnected (transmit stays off until you key)"), "info")
                return
            except Exception as e2:  # noqa: BLE001
                self._status(error=f"Device problem: {e2}")

    def _rx_block(self, x: np.ndarray):
        if self.reconf:
            self.reconf = False
            self._configure_rx()
        s = self.st
        self.rx_samples += len(x)
        rec = self.rec
        if rec is not None:
            # What the radio sent, DC and all: a recording is evidence, and
            # playing it back takes it through the blocker again.
            self._rec_push(rec, x)
        blk = self.dcblock
        if blk is not None:
            # A zero-IF receiver's DC spike out before anything looks at the
            # samples: scopes, demodulators, decoders (ohscore/dsp/dcblock.py).
            x = blk(x)
        t_stream = self.rx_samples / self.geo.fs
        if self.rx_invert:
            x = np.conj(x)
        # What a session holding the receiver (DAB) is fed: the device's own
        # samples, before the noise blanker, which would cut an OFDM block's
        # peaks as if they were impulses.
        raw = x
        if self.listening is not None:
            self._listen_wide(x)
        if s["nb"]:
            x = self.nb(x)
        X, starts = self.analysis.push(x)
        if X.shape[0] == 0:
            return
        if s["mode"] in ("usb", "lsb"):
            self._keep_recent(X, starts)
        elif self.recent is not None:
            self.recent = None
        now = time.time()

        # The app's trackers first, so every channel below uses this block's correction.
        self._rx_track(X, starts, t_stream)

        # Wide scope: crop to the app's span, report its corrected start.
        w_lo, w_hi = self.wide_span()
        for _, db in self.wide.process(x):
            dc = self._dc_mask(db) if blk is not None else None
            self._publish("wide", self._crop(db, self.wide.bin_hz, 0.0, w_lo, w_hi, now, dc=dc))
        self._rx_wide(x)

        # VFO audio.
        rx_dial = self._rx_dial(s)
        # An app's own demodulator (HAM's FM) never sets the core
        # demodulator's gain; cleared first, so it cannot carry a stale one.
        self.demod.gain = None
        self.heard_hi = None
        held = self.held
        if held is not None:
            # The receiver is the session's (hold_receiver): nothing at the
            # dial is demodulated, and what is heard is the session's sound.
            audio, level = self._held_block(X, raw)
        else:
            audio, level = self._demodulate(X, starts, rx_dial)
        self.rx_level = level
        # Full duplex by default: receive audio carries on while transmitting -
        # hearing your own downlink is how QO-100 is operated.
        vol = 0.0 if s["mute"] else s["volume"] * self._rx_audio_gain(s)
        if held is not None:
            if held.get("feed") is not None:
                # A hold that only listens (a band scan) makes no sound:
                # silence, so a stream stays a stream.
                sound = np.zeros(len(audio) * self.OUT_RATE // AUDIO_RATE, np.float32)
            else:
                sound = self.decoders.held_audio(len(audio) / AUDIO_RATE, self.OUT_RATE)
            if sound is not None:
                with self.play_lock:
                    self.audio.play(sound * np.float32(vol))
        else:
            # Noise reduction is for the ear only: the speaker gets `heard`,
            # the decoders below get `audio` as demodulated - they do better
            # on the raw passband than on audio a gain mask has worked on.
            heard = self._rx_heard(self.nr(audio, self.demod.gain))
            if not (s["mode"] == "freedv" and self.decoder is not None):
                # At OUT_RATE: the demodulator's own (wide FM's 48 kHz, never
                # through 12 kHz and back) or this block brought up to it.
                hi = self.heard_hi if self.heard_hi is not None else self._to_out(heard, self.out_up)
                with self.play_lock:
                    self.audio.play(hi * np.float32(vol))
        utc = self._audio_utc(now, len(audio))
        if self.decoder is not None and held is None:
            try:
                self.decode_q.put_nowait((audio, utc))
            except queue.Full:
                pass

        # Zoom scope around the dial (around the receiver's centre while a
        # hold that leaves the dial alone has it elsewhere: the dial is
        # then outside the span, and the zoom would show an alias).
        zc = rx_dial + s["zoomPan"]
        if held is not None and not held.get("dial", True):
            zc = held["centre"] + s["zoomPan"]
        self.zoom_ch.set_freq(self._off(zc))
        zy = self.zoom_ch.take(X, starts)
        for _, db in self.zoom_scope.process(zy):
            self._publish("zoom", self._crop(db, self.zoom_scope.bin_hz, zc, zc - s["zoomSpanHz"] / 2,
                                             zc + s["zoomSpanHz"] / 2, now, centred=True))

        # The app's consumers that follow the channels.
        self._rx_monitor(X, starts, t_stream)
        # The fixed decoder sessions' channels (ohscore/decoders.py), and the
        # device's own samples for a session holding the receiver, once the
        # retune that gave it the receiver has reached them.
        self.decoders.rx(X, starts, utc)
        if held is not None:
            if held.get("feed") is not None:
                held["feed"](raw, self._rx_settled())
            else:
                self.decoders.rx_held(raw, utc, self._rx_settled())

        if now >= self.meter_due:
            self.meter_due = now + 0.1
            self._publish("meter", {"t": now, "rx": round(self.rx_level, 1), "mic": round(self.mic_level, 1),
                                    "txPeak": round(self.tx_peak, 3), "keyed": s["keyed"], **self._meter_extra(s),
                                    **self._cw_meter(s)})
        self._rx_done(s)

    def _cw_meter(self, s: dict) -> dict:
        """`cwHearing` in CW: whether the decoder's squelch is open (shack_cw
        Decoder.hearing). The decoder only speaks when it prints a letter, so
        a speed it reported ("Decoder hears 22 wpm") had nothing to say it
        was over and stood for good after the signal went. It rides the
        meter, ten times a second, rather than becoming a decode event:
        every client's CW strip reads `events` as text, and an extra field
        in a meter is one each client can ignore."""
        hearing = getattr(self.decoder, "hearing", None) if s["mode"] == "cw" else None
        return {} if hearing is None else {"cwHearing": bool(hearing)}

    def _demodulate(self, X, starts, rx_dial: float) -> tuple[np.ndarray, float]:
        """The VFO channel at rx_dial to 12 kHz audio, and its level in dBFS."""
        self.vfo_ch.set_freq(self._off(rx_dial))
        iq = self.vfo_ch.take(X, starts)
        if self.listening is not None:
            self._listen_feed(iq, rx_dial)
        return self.demod(iq)

    # ------------------------------------------------------ receiver ownership
    # A decoder session that needs the whole receiver - DAB, a 1.536 MHz
    # block wanting at least 2.048 MS/s centred on it - takes it from the
    # operator while it runs, and says so (`rxOwner` in the state): the dial
    # goes to the block's centre, the receiver's centre (DC) onto it,
    # nothing at the dial is demodulated, and what is heard is the
    # session's sound. Ownership is explicit because the two cannot share:
    # while it holds the receiver every set() that would tune (HELD_KEYS)
    # is refused with a sentence, as is every key-up, rather than the
    # session being quietly starved or the operator quietly ignored. When it
    # stops - by the operator, or with the radio - the dial and mode from
    # before (HOLD_PRIOR) are put back.
    #
    # Tapping the stream instead, when the span already held the block, was
    # considered and left out: the block would vanish the moment anyone
    # tuned, and DAB's centre carrier is the one place in the block that
    # carries nothing, so a receiver centred on it loses nothing to its own
    # DC spur, where a block off to one side would.
    #
    # A hold may instead **give way** (`yields`, Radio's band scan): it
    # takes the receiver only while nobody wants it, and the moment anyone
    # does - a set() that changes anything, a key-up, a decoder, a
    # recording, a listener (client_activity) - `yields(why)` is called on
    # that caller's thread, which gives the receiver back (restoring what
    # it moved) before that caller goes on. Such a hold refuses nothing, so
    # it never shows in txBlocked. It may also keep more of the operator's
    # settings to put back (`keep`), and is fed the device's samples
    # (`feed(raw, settled)`) instead of a decoder session; it plays silence.
    # With `dial=False` it moves only the receiver's centre and leaves the
    # dial where the operator put it: what the transmit guard judges, what
    # a client shows and what a key-up returns to stay theirs throughout.
    def hold_receiver(self, sid: str, by: str, centre: float, label: str, min_rate: float, *,
                      yields=None, feed=None, keep: tuple = (), dial: bool = True) -> None:
        """Give the receiver to session `sid` (a `by` decoder on `label`,
        centred on `centre` Hz, needing `min_rate` S/s). Raises
        decoders.Refused with the code and sentence when it cannot."""
        # One that gives way gives way to this one, before the lock: giving
        # way puts settings back through set().
        self.preempt_receiver(by)
        with self.lock:
            why = self._hold_refusal(centre, min_rate)
            if why is not None:
                raise Refused(*why)
            prior = {k: self.st[k] for k in self.HOLD_PRIOR + tuple(keep) if k in self.st}
            self.held = {"session": sid, "by": by, "block": label, "centre": float(centre), "prior": prior,
                         "yields": yields, "feed": feed, "dial": dial}
        try:
            if dial:
                self._set_holding(vfo=float(centre))
        except ValueError as e:
            with self.lock:
                self.held = None
            raise Refused("out_of_range", str(e)) from None
        self.log.info("receiver held by %s session %s on %s (%.0f Hz); before: %s", by, sid, label, centre, prior)
        self._status(rxOwner=self._owner_view())
        self._derive()
        self._held_retune()

    def release_receiver(self, sid: str) -> None:
        """Session `sid` lets the receiver go: the operator's dial and mode
        from before it, and the receiver back to following the dial."""
        with self.lock:
            h = self.held
            if h is None or h["session"] != sid:
                return
            self.held = None
        try:
            # All of it in one set(), so a value that follows another (the
            # repeater offset arriving back on a band) is the one kept, and
            # as the holder: Settings-only keys a band scan keeps, such as
            # the sample rate, are put back by the engine, never refused as
            # if a client had asked; unchanged, they change nothing.
            if any(self.st.get(k) != v for k, v in h["prior"].items()):
                self._set_holding(authorise=True, **h["prior"])
        except ValueError as e:
            # A dial the radio can no longer reach (another device since):
            # the receiver is the operator's again wherever it is.
            self.log.warning("could not put the dial back after %s: %s", sid, e)
            self.toast(_("The dial could not be put back: {error}").format(error=e), "warn")
        self.log.info("receiver released by %s session %s", h["by"], sid)
        self._status(rxOwner={})
        self._derive()
        self._held_retune()

    def rename_hold(self, old: str, sid: str) -> None:
        """The holder's id once it has one: the decoders hold the receiver
        under a placeholder while the session is made, so a refusal comes
        before any session exists."""
        with self.lock:
            if self.held is not None and self.held["session"] == old:
                self.held["session"] = sid
        self._status(rxOwner=self._owner_view())

    def move_hold(self, sid: str, centre: float, label: str | None = None) -> bool:
        """The holder `sid` retunes the receiver it holds (a band scan's
        next hop): the dial and the receiver's centre to `centre`. False,
        and nothing moved, when `sid` no longer holds it."""
        with self.lock:
            h = self.held
            if h is None or h["session"] != sid:
                return False
            h["centre"] = float(centre)
            if label is not None:
                h["block"] = label
        if h.get("dial", True):
            self._set_holding(vfo=float(centre))
        self._status(rxOwner=self._owner_view())
        self._held_retune()
        return True

    def preempt_receiver(self, why: str) -> bool:
        """A hold that gives way (`yields`) gives the receiver back now,
        on this thread; True if one did. Nothing for any other hold."""
        h = self.held
        fn = h.get("yields") if h is not None else None
        if fn is None:
            return False
        fn(why)
        return True

    def client_activity(self, what: str) -> None:
        """Someone did something with the radio (`what`: "set", "listener",
        "transmit", "decoder", "recording", "playback", "tune"): a hold
        that gives way does, and the activity hooks hear of it."""
        if not getattr(self._hold_tls, "on", False):
            self.preempt_receiver(what)
        for fn in list(self.activity_hooks):
            try:
                fn(what)
            except Exception:  # noqa: BLE001 - a hook's fault costs the hook, never the caller
                self.log.warning("activity hook failed", exc_info=True)

    def _set_holding(self, authorise: bool = False, **changes) -> dict:
        """set() on behalf of the session holding the receiver, which alone
        may tune it. A flag of this thread's, so an operator's set() arriving
        on another thread meanwhile is still refused."""
        self._hold_tls.on = True
        try:
            return self.set(authorise=authorise, **changes)
        finally:
            self._hold_tls.on = False

    def _owner_view(self) -> dict:
        h = self.held
        if h is None:
            return {}
        return {"by": h["by"], "session": h["session"], "block": h["block"], "freqHz": h["centre"],
                "prior": dict(h["prior"]), "text": self._held_why(h, "tune")}

    def _held_why(self, h: dict, doing: str) -> str:
        """The sentence for what a held receiver refuses: `doing` "tune" (a
        set() that would move it) or "transmit" (a key-up). A hold that
        gives way refuses neither; its sentence says what it is doing."""
        if h.get("yields") is not None:
            return self._yielding_why(h)
        if doing == "transmit":
            return _("The receiver is playing DAB from block {block}: stop the DAB station to transmit").format(
                block=h["block"])
        return _("The receiver is playing DAB from block {block}: stop the DAB station to tune or change "
                 "mode").format(block=h["block"])

    def _yielding_why(self, h: dict) -> str:
        """What a hold that gives way says it is doing (rxOwner's text)."""
        return _("The receiver is busy on {label}; it is yours again the moment you use it").format(
            label=h["block"])

    def _hold_refusal(self, centre: float, min_rate: float) -> tuple[str, str] | None:
        """(code, sentence) when the receiver cannot be held now, else None
        (called under the lock)."""
        if not self.HOLDS_RECEIVER:
            return "decoder_unavailable", _("This app's receiver stays on its own frequencies and cannot play DAB")
        if not self.running or self.dev is None:
            return "not_running", _("Start the radio before adding a decoder")
        if self.st["keyed"] or (self.tx_thread is not None and self.tx_thread.is_alive()):
            return "on_air", _("Not while transmitting: DAB takes the receiver to Band III")
        if self.held is not None:
            return "receiver_busy", _("A DAB station on block {block} already has the receiver: stop it "
                                      "first").format(block=self.held["block"])
        if self.play is not None:
            return "receiver_busy", _("Not while a recording is playing: stop it first")
        fs = float(self.geo.fs)
        if fs < min_rate:
            return "rate_too_low", self._rate_sentence(min_rate, fs)
        return None

    def _rate_sentence(self, least: float, fs: float) -> str:
        """Why the receiver is too slow for a held session, and what to do
        about it when this radio has a faster rate. Changing the rate
        reopens the radio (a restart), which on a controller gives the
        broker's claim back and takes it again, so it is the operator's
        choice and never done behind their back."""
        faster = self._faster_rate(least)
        if faster:
            return _("DAB needs the receiver to run at {least:g} MS/s or more, and the {device} runs at {rate:g} "
                     "MS/s: choose {faster:g} MS/s in Settings › Radio (the radio restarts)").format(
                least=least / 1e6, device=self._kind(), rate=fs / 1e6, faster=faster / 1e6)
        return _("DAB needs the receiver to run at {least:g} MS/s or more, and the {device} cannot (it runs at "
                 "{rate:g} MS/s)").format(least=least / 1e6, device=self._kind(), rate=fs / 1e6)

    def _faster_rate(self, least: float) -> float | None:
        """A rate of at least `least` this radio could be set to, or None."""
        return None

    def _kind(self) -> str:
        return str(getattr(self.dev, "kind", "") or self.cfg.get("device", ""))

    def _held_retune(self) -> None:
        """Move the receiver's centre now the hold has begun or ended (an
        app that retunes its hardware to its dial)."""

    # ------------------------------------------------- the pinned span
    # Background decoder sessions (fixed ones: not the mode's, not one
    # holding the receiver) want their frequencies to stay in the span
    # however the operator tunes. An app whose receiver centre follows its
    # dial (PINS_SPAN: Radio) pins the centre while any run: the dial moves
    # freely inside the span, the centre stays, and a tune that would leave
    # the span is refused (SpanPinned) unless the operator lets it stop
    # them. The hooks below are that app's; here they do nothing, so an
    # engine that does not pin keeps the `outside` rule (decoders.py).
    def pin_plan(self, freq: float, half_width: float) -> float | None:
        """The centre that holds every background session, a new one at
        `freq` (± `half_width`) and the dial; raises decoders.Refused
        `outside_span` when none does. None: this engine does not pin."""
        return None

    def pin_to(self, centre: float) -> None:
        """Pin the receiver's centre at `centre` (a new session fitted)."""

    def span_changed(self) -> None:
        """The background sessions changed: unpin when none is left, and
        say so in `span`."""

    def span_view(self) -> dict:
        """`span` in the state: {centreHz, loHz, hiHz, pinned, by,
        sessions}; {} for an engine that does not pin."""
        return {}

    def _pin_check(self, clean: dict, drop: bool) -> None:
        """set(): refuse (SpanPinned) a change that would take the dial
        out of the pinned span, or stop the sessions first when `drop`."""

    def _held_block(self, X, raw: np.ndarray) -> tuple[np.ndarray, float]:
        """A held block's 12 kHz audio (silence: the mode decoder and the
        timing still count blocks) and its level, the whole block's power
        in dBFS, for the meter."""
        n = X.shape[0] * (self.geo.L // self.geo.decimation_for(AUDIO_RATE))
        p = float(np.mean(np.abs(raw) ** 2)) if len(raw) else 0.0
        return np.zeros(n, np.float32), 10 * math.log10(p + 1e-20)

    # ------------------------------------------------ auto-tune and best audio
    # Both listen to the receive channel (the VFO channel's IQ, before the
    # demodulator: the coarse stage needs both sides of the dial), work on
    # a thread of their own and apply the result once through set(), like
    # any other control change. Best audio listens for a fixed few seconds;
    # auto-tune looks after a few seconds and again every second after,
    # until it is sure or autotune.LISTEN_SECONDS have gone by
    # (autotune.Listener), with `autoHeard` counting the seconds. Neither
    # ever keeps adjusting: whatever the operator does afterwards stands.
    def auto_tune(self, dial: float | None = None) -> None:
        """Land the SSB station near the receive dial (ohscore/dsp/autotune.py).
        With `dial`, the receive dial is moved there first (a click or a
        right-click on a scope: the frequency under the mouse). Returns at
        once; the result arrives as a toast and in `autoTune` (or, refused,
        `autoTuneRefused`). Retunes `vfo` - or `rit` while RIT is on, so a
        transmit frequency the operator chose to keep stays where it is.
        Raises ValueError (a sentence) when it cannot start."""
        self._listen_start("tune", dial)

    def best_audio(self) -> None:
        """Choose the receive filter, AGC, noise reduction and noise
        blanker for the station on the dial (ohscore/dsp/autoaudio.py) and
        apply them once. Result in `autoAudio` / `autoAudioWhy` (refused:
        `autoAudioRefused`) and a toast. Raises ValueError when it cannot
        start."""
        self._listen_start("audio", None)

    LISTEN_KINDS = {"tune": "auto-tune", "audio": "best audio"}

    # LISTEN_KINDS names each kind for code; a sentence about one is written
    # whole for each kind, since a translation cannot drop a translated
    # name into its own word order (or capitalise it as English does).
    def _already_listening(self) -> str:
        return (_("Already listening for auto-tune") if self.listening["kind"] == "tune"
                else _("Already listening for best audio"))

    def _listen_start(self, kind: str, dial: float | None) -> None:
        self.client_activity("tune")
        what = self.LISTEN_KINDS[kind]
        if kind == "tune" and dial is None and self._try_guess():
            return
        if kind == "tune":
            self.tune_guess = None
        with self.lock:
            if not self.running:
                raise ValueError(_("The radio is not running, so there is nothing to listen to for auto-tune")
                                 if kind == "tune" else
                                 _("The radio is not running, so there is nothing to listen to for best audio"))
            if self.st["mode"] not in ("usb", "lsb"):
                msg = (_("Auto-tune works on USB and LSB voice; the mode is {mode}") if kind == "tune"
                       else _("Best audio works on USB and LSB voice; the mode is {mode}"))
                raise ValueError(msg.format(mode=self.st["mode"].upper()))
            if self.listening is not None:
                raise ValueError(self._already_listening())
        if dial is not None:
            dial = self._carrier_near(float(dial), self.st["mode"])
            target = dial - (self.st["rit"] if self.st["ritOn"] else 0.0)
            self.set(vfo=target)
        secs = autotune.LISTEN_SECONDS if kind == "tune" else autoaudio.CAPTURE_SECONDS
        with self.lock:
            if self.listening is not None:
                raise ValueError(self._already_listening())
            L = self.listening = {"kind": kind, "dial": self._rx_dial(self.st), "mode": self.st["mode"],
                                  "need": int(secs * AUDIO_RATE), "chunks": [], "n": 0, "impulses": 0,
                                  "wide": 0, "threshold": float(self.st["nbThreshold"]), "more": threading.Event()}
            if kind == "tune":
                L["listener"] = autotune.Listener(L["mode"], AUDIO_RATE, most=secs)
        # The last refusal of this kind is cleared, so the same sentence
        # again is news to the UI.
        self._status(autoBusy=kind, autoHeard=0, **{"autoTuneRefused" if kind == "tune" else "autoAudioRefused": ""})
        if kind == "tune":
            threading.Thread(target=self._tune_worker, args=(L,), name=f"{self.THREAD_PREFIX}-listen",
                             daemon=True).start()

    # How much of the recent receive spectrum (the analysis bank's frames,
    # kept by reference - no copy) a right-click's auto-tune looks back at
    # to put the dial on the station before listening (_carrier_near).
    # On the 07/10/2026 recordings the spectrum-alone estimate from the
    # middle of a station found a band in 1 s of 81 % of windows, in 2 s of
    # 92 % and was no better placed with 4; 2 s at 1.2 MS/s is 26 MB.
    RECENT_SECONDS = 2.0

    def _keep_recent(self, X: np.ndarray, starts: np.ndarray) -> None:
        r = self.recent
        if r is None or r[0] is not self.geo:
            r = self.recent = (self.geo, deque())
        q = r[1]
        q.append((X, starts))
        keep = int(self.RECENT_SECONDS * self.geo.fs / self.geo.L)
        while len(q) > 1 and sum(len(a) for a, _ in q) - len(q[0][0]) >= keep:
            q.popleft()

    def _carrier_near(self, dial: float, mode: str) -> float:
        """Where a right-click's auto-tune should listen from: the suppressed
        carrier of the voice under the mouse as the last two seconds of the
        spectrum place it (autotune.coarse: the band's carrier-side edge,
        less the usual low cut), or the click itself when nothing there
        looks like a voice.

        A click lands on the middle of the signal on the scope, and the dial
        is the carrier, so listening from the click left half the voice
        outside the receive filter while it listened - and wherever a
        refusal left it, which is what Brian saw on 07/10/2026 ("it picks
        the middle of the signal rather than the signal filling between
        the dotted lines"). The measurement itself does not need this - it
        works on both sides of the dial, and answered the same from the
        middle as from near the carrier on the recordings - but the
        operator hears the station properly while it listens, and a
        refusal leaves the voice in the passband to within the edge's
        error (a hundred hertz or two), not half out of it."""
        r = self.recent
        if r is None or r[0] is not self.geo or not r[1]:
            return dial
        q = list(r[1])          # one C call: the receive thread cannot change it midway
        X = np.concatenate([a for a, _ in q])
        starts = np.concatenate([b for _, b in q])
        ch = Channel(self.geo, self.geo.decimation_for(AUDIO_RATE), freq=self._off(dial))
        iq = ch.take(X, starts)
        try:
            c, band, _why = autotune.coarse(iq, mode)
        except Exception:  # noqa: BLE001 - a hint only: never stop the request
            self.log.exception("auto-tune: spectrum estimate before listening failed")
            return dial
        # Only the signal under the mouse: when it paused, coarse() may have
        # taken a neighbour, and the click is the better guess then.
        if c is None or not (band[0] - 100.0 <= 0.0 <= band[1] + 100.0):
            return dial
        return dial + round(c / 10.0) * 10.0

    # How long an auto-tune's guesses stay on offer: long enough to read the
    # toast, listen and press again; short enough that a press minutes
    # later, at a station that has moved on, listens afresh.
    GUESS_SECONDS = 30.0

    def _offer_guesses(self, L: dict, r) -> str:
        """Keep an unsure refusal's guesses (autotune.Listener: where the
        voice fitted best, and what fitted nearly as well) for the next
        presses, and return the sentence that offers them, or "".

        On air on 07/10 and 17/10/2026 most refusals of a genuine voice
        were ties - two offsets a pitch apart, the parts of a short over
        disagreeing, a best fit nearer the voice's edge than most
        transmitters' - and on the 17/10 recordings the first guess was the
        station in about four refusals in five (tools/autotune_replay.py).
        Applying it would be a wrong tune whenever it is not; refusing left
        the operator nothing to do but press again and wait another 12 s.
        Which of two offsets a pitch apart is right is what an ear hears at
        once (one voice sounds natural, the other high or low), so the
        guesses are offered: the next press tries the best, the one after
        the other, the one after that goes back to where the listen began."""
        g = [round(x) for x in (r.details or {}).get("guesses") or []]
        if not g:
            return ""
        steps = [(x, "guess") for x in g] + [(0, "start")]
        self.tune_guess = {"dial": L["dial"], "mode": L["mode"], "at": L["dial"], "steps": steps, "next": 0,
                           "until": time.monotonic() + self.GUESS_SECONDS}
        if len(g) == 1:
            return " " + _("Best guess {shift:+d} Hz: press Auto-tune again to try it.").format(shift=g[0])
        return " " + _("Best guess {shift:+d} Hz, or {other:+d} Hz: press Auto-tune again to try each in turn "
                       "and keep the one whose voice sounds right.").format(shift=g[0], other=g[1])

    def _offer_other(self, L: dict, r, shift: int) -> str:
        """After an answer, keep the next best fit a pitch away on offer for
        a second press (autotune: `alt`), and return the sentence saying so.
        A wrong answer is the comb a pitch off; on 17/10/2026 one station's
        first looks were, and pressing again only measured the same pitch
        again. One more press now moves there, one after comes back."""
        alt = (r.details or {}).get("alt")
        if alt is None:
            return ""
        alt = round(alt)
        steps = [(alt, "other"), (shift, "measured")]
        self.tune_guess = {"dial": L["dial"], "mode": L["mode"], "at": self._rx_dial(self.st), "steps": steps,
                           "next": 0, "until": time.monotonic() + self.GUESS_SECONDS}
        return _("If the voice sounds wrong, press Auto-tune again within {s:.0f} s for the next best fit "
                 "({shift:+d} Hz from here).").format(s=self.GUESS_SECONDS, shift=alt - shift)

    def _try_guess(self) -> bool:
        """A press of auto-tune while guesses are on offer (_offer_guesses,
        _offer_other) and nothing has moved since: move to the next of them
        at once, saying so, and return True."""
        g = self.tune_guess
        with self.lock:
            if g is None or not self.running or time.monotonic() > g["until"]:
                self.tune_guess = None
                return False
            s = self.st
            if s["mode"] != g["mode"] or self._rx_dial(s) != g["at"] or self.listening is not None:
                self.tune_guess = None
                return False
            off, kind = g["steps"][g["next"]]
            shift = round(g["dial"] + off - self._rx_dial(s))
            rit = bool(s["ritOn"])
            vfo, rit_hz = float(s["vfo"]), float(s["rit"])
        try:
            if rit:
                self.set(rit=rit_hz + shift)
            else:
                self.set(vfo=vfo + shift)
        except ValueError as e:
            self.tune_guess = None
            self._listen_done("tune", refused=_("the station is {shift:+d} Hz away but the {why}").format(
                shift=shift, why=e))
            return True
        g["at"] = self._rx_dial(self.st)
        g["next"] += 1
        g["until"] = time.monotonic() + self.GUESS_SECONDS
        last = g["next"] >= len(g["steps"])
        if last:
            self.tune_guess = None
        n_guesses = sum(k == "guess" for _o, k in g["steps"])
        if kind == "start":
            text = _("Auto-tune: back where it listened ({shift:+d} Hz); press again to listen afresh")
            status = _("{shift:+d} Hz, back where it listened")
        elif kind == "measured":
            text = _("Auto-tune: back on what it measured ({shift:+d} Hz); press again to listen afresh")
            status = _("{shift:+d} Hz, back on what it measured")
        elif kind == "other":
            text = _("Auto-tune: moved {shift:+d} Hz to the next best fit, not what it measured; press again "
                     "to go back")
            status = _("{shift:+d} Hz, the next best fit, not measured for sure")
        elif g["steps"][g["next"]][1] == "start":
            text = _("Auto-tune: moved {shift:+d} Hz to its guess {n} of {m}, not measured for sure; press again "
                     "to go back")
            status = _("{shift:+d} Hz, a guess, not measured for sure")
        else:
            text = _("Auto-tune: moved {shift:+d} Hz to its guess {n} of {m}, not measured for sure; press again "
                     "for the next")
            status = _("{shift:+d} Hz, a guess, not measured for sure")
        self._status(autoTune=status.format(shift=shift), autoTuneRefused="")
        self.toast(text.format(shift=shift, n=g["next"], m=n_guesses), "info")
        return True

    def _listen_wide(self, x: np.ndarray) -> None:
        """Best audio counts impulses where the noise blanker would see
        them: on the wideband stream, before any blanking."""
        L = self.listening
        if L is not None and L["kind"] == "audio":
            L["impulses"] += autoaudio.count_impulses(x, L["threshold"])
            L["wide"] += len(x)

    def _listen_feed(self, iq: np.ndarray, rx_dial: float) -> None:
        L = self.listening
        if L is None or L.get("done"):
            return
        if not L["n"] and self._rx_dial(self.st) == L["dial"] and (rx_dial != L["dial"]
                                                                    or not self._rx_settled()):
            # A block from before the request's own retune: either one the
            # receive thread was already demodulating at the old dial when
            # the request began (it read the dial before the retune - a
            # right-click always retunes - and only reached here after), or
            # one at the new dial whose samples the hardware took before it
            # had moved there (_rx_settled). The dial is where the request
            # put it, so neither is a change: the next blocks are the new
            # dial's. Refusing the first kind made the right-click refuse
            # at once, twice in a row, on air on 07/10/2026. Only before
            # anything is collected: once audio has been gathered, a block
            # at another dial means the dial moved and came back, and what
            # was heard is of two places.
            return
        if rx_dial != L["dial"] or self.st["mode"] != L["mode"]:
            # What has been heard so far is of another frequency or mode.
            if self._listen_claim(L):
                self._listen_done(L["kind"], refused="the dial or the mode changed while listening; try again")
            return
        L["chunks"].append(np.array(iq, np.complex64))
        L["n"] += len(iq)
        if L["kind"] == "tune":
            # The listener's own thread looks when it is due (_tune_worker);
            # the receive thread only collects, and says how long it has
            # heard once a second.
            if L["n"] >= L["need"]:
                L["done"] = True
            heard = L["n"] // AUDIO_RATE
            if heard != L.get("heard"):
                L["heard"] = heard
                self._status(autoHeard=int(heard))
            L["more"].set()
        elif L["n"] >= L["need"]:
            L["done"] = True
            iq_all = np.concatenate(L["chunks"])[:L["need"]]
            wide_s = L["wide"] / self.geo.fs if L["wide"] else 0.0
            rate = L["impulses"] / wide_s if wide_s else 0.0
            threading.Thread(target=self._listen_analyse, args=(L, iq_all, rate),
                             name=f"{self.THREAD_PREFIX}-listen", daemon=True).start()

    def _rx_settled(self) -> bool:
        """Whether the receive channel now carries what the dial says
        (an app that retunes the hardware to follow the dial - HAM - says
        False until the retune has reached the samples)."""
        return True

    def _listen_claim(self, L: dict) -> bool:
        """End request L, if it is still the one listening: True for the
        one caller that gets to report its outcome. The receive thread
        abandons a request when the dial moves while the analysis thread
        may be finishing it; without this both could report, and the
        second would report a request already over."""
        with self._listen_lock:
            if self.listening is not L:
                return False
            self.listening = None
            return True

    def _tune_worker(self, L: dict) -> None:
        """Auto-tune's own thread: a look at what has been heard whenever
        the listener is due one (autotune.Listener.due), until it answers,
        refuses, or the request is abandoned (the dial or mode moved, the
        radio stopped) - then it just stops, saying nothing; whoever
        abandoned it has said why. A look that takes longer than a second
        of audio only means the next look sees more."""
        lis = L["listener"]
        try:
            while self.listening is L:
                n = min(L["n"], L["need"])
                if not lis.due(n):
                    L["more"].wait(0.25)
                    L["more"].clear()
                    continue
                iq = np.concatenate(list(L["chunks"]))[:n]
                r = lis.look(iq)
                if r is None:
                    continue
                if not self._listen_claim(L):
                    return
                if not r.ok:
                    self._listen_done("tune", refused=self._heard_for(r) + r.why + self._offer_guesses(L, r))
                    return
                self._apply_tune(L, r)
                return
        except Exception as e:  # noqa: BLE001 - a bug here must not leave the request hanging
            self.log.exception("auto-tune failed")
            if self._listen_claim(L):
                self._listen_done("tune", refused=f"it failed ({e})")

    @staticmethod
    def _heard_for(r) -> str:
        """"after 12 s, " for a refusal that came of listening to the end;
        nothing for one that came at once (nothing there, not a voice)."""
        heard = (r.details or {}).get("heard")
        return f"after {heard:.0f} s, " if heard and heard > autotune.CAPTURE_SECONDS else ""

    def _listen_analyse(self, L: dict, iq: np.ndarray, impulse_rate: float) -> None:
        """Best audio's analysis, on its fixed capture."""
        try:
            c = autoaudio.best_audio(iq, L["mode"], impulse_rate)
            if not self._listen_claim(L):
                return
            if not c.ok:
                self._listen_done("audio", refused=c.why)
                return
            self.set(**c.settings)
            why = "\n".join(f"{k}: {s}" for k, s in c.reasons)
            self._status(autoAudio=c.summary(), autoAudioWhy=why)
            self._listen_done("audio", text=f"Best audio: {c.summary()}")
        except Exception as e:  # noqa: BLE001 - a bug here must not leave the request hanging
            self.log.exception("best audio failed")
            if self._listen_claim(L):
                self._listen_done("audio", refused=f"it failed ({e})")

    def _apply_tune(self, L: dict, r) -> None:
        s = self.st
        if self._rx_dial(s) != L["dial"]:
            self._listen_done("tune", refused="the dial moved while the voice was being measured; try again")
            return
        shift = round(r.offset)
        side = L["mode"].upper()
        heard = (r.details or {}).get("heard")
        detail = (f"{side}, pitch {r.pitch:.0f} Hz, {r.voiced} voiced frames"
                  + (f" in {heard:.0f} s" if heard else "") + f", spectrum alone said {r.coarse:+.0f} Hz"
                  + (", landed on its leaked carrier" if (r.details or {}).get("how") == "line" else ""))
        try:
            if s["ritOn"]:
                self.set(rit=float(s["rit"]) + shift)
                where = "RIT"
            else:
                self.set(vfo=float(s["vfo"]) + shift)
                where = "dial"
        except ValueError as e:
            self._listen_done("tune", refused=f"the station is {shift:+d} Hz away but the {e}")
            return
        self._status(autoTune=f"{shift:+d} Hz ({detail})")
        other = self._offer_other(L, r, shift)
        self._listen_done("tune", text=f"Auto-tune: {where} moved {shift:+d} Hz onto the station ({detail})"
                          + (" " + other if other else ""))

    def _listen_done(self, kind: str, text: str = "", refused: str = "") -> None:
        if refused:
            key = "autoTuneRefused" if kind == "tune" else "autoAudioRefused"
            self._status(autoBusy="", **{key: refused})
            self.toast((_("Auto-tune refused: {why}") if kind == "tune" else _("Best audio refused: {why}")).format(
                why=refused), "warn")
        else:
            key = "autoTuneRefused" if kind == "tune" else "autoAudioRefused"
            self._status(autoBusy="", **{key: ""})
            self.toast(text, "info")

    def _rx_audio_gain(self, s: dict) -> float:
        """Factor on the receive volume (an app that is half duplex returns
        0 while keyed)."""
        return 1.0

    def _rx_wide(self, x: np.ndarray) -> None:
        """The app's consumer of the wideband block, as the wide scope gets
        it (after the noise blanker), on the receive thread."""

    def _rx_heard(self, heard: np.ndarray) -> np.ndarray:
        """What the speaker plays for this block of receive audio, before
        volume and mute (default: the receive audio itself)."""
        return heard

    def _rx_track(self, X, starts, t_stream: float) -> None:
        """Receive consumers that run before the channels."""

    def _rx_monitor(self, X, starts, t_stream: float) -> None:
        """Receive consumers that run after the channels."""

    def _rx_done(self, s: dict) -> None:
        """Last thing in each receive block (NB: re-centre the hardware)."""

    def _meter_extra(self, s: dict) -> dict:
        """The app's fields in the meter feed."""
        return {}

    def _audio_utc(self, now: float, n: int) -> float:
        """UTC of the first sample of a just-demodulated audio block, for the
        decoders' slot timing (FT8 needs it to a fraction of a second). A real
        device delivers in real time, so the wall clock (less the block) is
        right and cannot drift; a simulator running faster than real time
        has its own clock, which its FT8 slots follow, and so does a
        recording being played (own_clock: the UTC just after the block
        read is `utc_end`), whose signals belong to when they were sent."""
        if getattr(self.dev, "own_clock", False):
            return self.dev.utc_end - n / AUDIO_RATE
        if getattr(self.dev, "realtime", True) is False and hasattr(self.dev, "t_epoch"):
            return self.dev.t_epoch + self.rx_samples / self.geo.fs - n / AUDIO_RATE
        # Stamped from the sample count against a slowly-followed epoch, not
        # from each block's own arrival time: the decoders place audio in
        # their slot by its stamp, and a block's arrival jitters by
        # milliseconds (thread scheduling, USB buffers). Stamping each block
        # with `now` gave every 75 ms seam a gap or an overlap of tens of
        # samples, which broke FT8's phase continuity badly enough that jt9
        # decoded almost nothing from a clean simulated band in real time
        # (it decoded everything from the same band run faster than real
        # time, which was stamped from the sample count). The epoch follows
        # the wall clock at 0.2 % a block (a tenth of a sample a block for 4 ms
        # of jitter), and is re-anchored after a stall or
        # a reconnect (more than 0.25 s out).
        est = now - self.rx_samples / self.geo.fs
        e0 = getattr(self, "_utc0", None)
        if e0 is None or abs(est - e0) > 0.25:
            e0 = est
        else:
            e0 += 0.002 * (est - e0)
        self._utc0 = e0
        return e0 + self.rx_samples / self.geo.fs - n / AUDIO_RATE

    def _crop(self, db: np.ndarray, bin_hz: float, centre_dl: float, lo_dl: float, hi_dl: float, t: float,
              centred: bool = False, dc: tuple[int, int] | None = None):
        """Spectrum item (t, start_dial_hz, bin_hz, db) covering [lo_dl, hi_dl].
        For the wide scope, centre_dl is unused: bins are placed through the
        app's frequency model (NB's puts beacons on their nominal frequencies).
        `dc`: the bins of `db` _dc_mask filled in, carried into the item's
        own numbering as `dc_bins` when any of them is in it."""
        n = len(db)
        if centred:
            # Zoom: DC of the zoom channel is exactly centre_dl (corrected).
            i0 = int(math.floor((lo_dl - centre_dl) / bin_hz)) + n // 2
            i1 = int(math.ceil((hi_dl - centre_dl) / bin_hz)) + n // 2
            i0, i1 = max(0, i0), min(n, i1)
            start = centre_dl + (i0 - n // 2) * bin_hz
        else:
            i0 = int(math.floor(self._off(lo_dl) / bin_hz)) + n // 2
            i1 = int(math.ceil(self._off(hi_dl) / bin_hz)) + n // 2
            i0, i1 = max(0, i0), min(n, i1)
            # bin i sits at offset (i - n/2) * bin_hz from DC.
            start = self._dial_at((i0 - n // 2) * bin_hz)
        line = Line((t, float(start), float(bin_hz), db[i0:i1].copy()))
        if dc is not None:
            lo, hi = max(dc[0], i0) - i0, min(dc[1], i1 - 1) - i0
            if lo <= hi:
                line.dc_bins = (lo, hi)
        return line

    def _dc_mask(self, db: np.ndarray) -> tuple[int, int] | None:
        """Fill in the wide scope's bins over DC (bin n/2 of the shifted
        spectrum) with a straight line between their neighbours, in place:
        display only, so the line the blocker leaves - and the LO's phase
        noise around it - never stands down the waterfall. Answers the bins
        filled (inclusive), for the feed's `dcBins`."""
        n, k = len(db), self.DC_MASK_BINS
        lo, hi = n // 2 - k, n // 2 + k
        if lo < 1 or hi > n - 2:
            return None
        a, b = float(db[lo - 1]), float(db[hi + 1])
        db[lo:hi + 1] = np.linspace(a, b, hi - lo + 3, dtype=np.float32)[1:-1]
        return lo, hi

    def _decode_loop(self):
        while not self.stop_ev.is_set():
            item = self.decode_q.get()
            self._close_retired()
            if item is None:
                break
            dec = self.decoder
            if dec is None:
                continue
            try:
                dec.feed(item[0], item[1])
            except Exception as e:  # noqa: BLE001 - a decoder bug costs decodes, not the radio
                self.log.warning("decoder %s failed: %s", self.decoder_mode, e)
                self.retired.append(dec)
                self.decoder = None
                self.toast(_("The {mode} decoder stopped: {error}").format(mode=self.decoder_mode, error=e), "warn")

    # ------------------------------------------------------------------ transmit
    def _occupied(self, mode: str, dial: float, audio: np.ndarray | None = None) -> tuple[float, float]:
        s = self.st
        if audio is not None and len(audio):
            # Measure what we are actually about to send: the band holding
            # 99.5 % of the audio's power.
            A = np.abs(np.fft.rfft(audio)) ** 2
            f = np.fft.rfftfreq(len(audio), 1 / AUDIO_RATE)
            c = np.cumsum(A) / (A.sum() + 1e-30)
            lo = f[np.searchsorted(c, 0.0025)]
            hi = f[min(len(f) - 1, np.searchsorted(c, 0.9975))]
            return dial + lo, dial + hi
        if mode == "cw":
            return dial + s["cwPitch"] - 50.0, dial + s["cwPitch"] + 50.0
        if mode == "lsb":
            return dial - s["txFilterHi"], dial - s["txFilterLo"]
        return dial + s["txFilterLo"], dial + s["txFilterHi"]

    def _occupied_now(self, req: dict | None) -> tuple[float, float] | None:
        """The band an over measured at key-up (send() measures the rendered
        audio), where it is now: the transmitter follows the dial, so a
        band measured at `occupied_dial` has moved with it. The re-check
        when the dial moves used the band where it was measured, so a send
        could be tuned onto a beacon, or out of the licence, and was never
        refused."""
        occ = req.get("occupied") if req else None
        if occ is None:
            return None
        shift = self._tx_dial(self.st) - req.get("occupied_dial", self._tx_dial(self.st))
        return occ[0] + shift, occ[1] + shift

    def _tx_blocked(self, occupied: tuple[float, float] | None, req: dict | None = None) -> str:
        s = self.st
        if not self.running:
            return "The radio is not running"
        held = self.held
        if held is not None and held.get("yields") is None:
            # Before everything else: the receiver is tuned to a broadcast
            # block, wherever the dial was, and keying there means nothing.
            return self._held_why(held, "transmit")
        mode = self._judged_mode(req)
        if mode in modes_glue.RX_ONLY_MODES:
            # Before the device and the licence: true on every radio and at
            # every dial, so it is the sentence an operator needs.
            return self._rx_only_why(mode)
        if self.dev is None or not self.dev.can_tx:
            return getattr(self.dev, "tx_refusal", "") or "This device is receive-only"
        return self._tx_guard(mode, self._tx_dial(s), occupied, req)

    @staticmethod
    def _rx_only_why(mode: str) -> str:
        return _("{mode} is for listening only: nothing is ever transmitted in it").format(mode=mode_label(mode))

    def _judged_mode(self, req: dict | None) -> str:
        """The mode an over is judged in: its own for one of OVER_MODES,
        otherwise the radio's (which every other over is sent in: send()
        insists, and PTT keys in it)."""
        mode = (req or {}).get("mode")
        return mode if mode in self.OVER_MODES else self.st["mode"]

    def _tx_guard(self, mode: str, dial: float, occupied: tuple[float, float] | None,
                  req: dict | None = None) -> str:
        """'' if a transmission in `mode` from `dial`, occupying `occupied`
        (or, if None, what _occupied says the mode would), may go ahead;
        else the sentence saying why not. `req` is the request being judged
        (None: an ordinary over, for the idle status). It is passed rather
        than read from tx_req because at key-up tx_req still holds the
        previous over's request: HAM judged a plain over after a Tune at
        the Tune's share of drive, and a Tune at the full drive."""
        raise NotImplementedError

    def ptt(self, on: bool) -> None:
        """Key (voice: mic audio; CW: a steady carrier at the pitch) or unkey.
        Raises TxRefused (a ValueError) with the reason if keying is refused.
        Any PTT, press or release, also ends a voice keyer loop: the
        operator has taken over."""
        self.heartbeat()
        self._keyer_cancel("PTT")
        if not on:
            self._release()
            return
        if self.st["keyed"]:
            return
        self._key(self._ptt_req(self.st["mode"]))

    def _ptt_req(self, mode: str) -> dict:
        """The request PTT keys with in `mode`; a voice memory is this with
        its recording added (send_voice)."""
        src = "tune" if mode == "cw" else "ptt"
        req = {"source": src, "mode": mode, "audio": None}
        if mode == "freedv":
            req["stream"] = modes_glue.streamer("freedv", self.st["freedvMode"])
            if req["stream"] is None:
                raise TxRefused(f"FreeDV cannot transmit here: {self.modes_info.get('freedv', {}).get('missing', '')}")
        return req

    @staticmethod
    def _voice_over(req: dict) -> bool:
        """Whether an over is speech through the voice chain (mic gain,
        compressor, the transmit filter): PTT in a voice mode, or a voice
        memory - never a rendered message or a tune carrier."""
        return req["mode"] != "cw" and (req["source"] == "ptt" or req.get("memory") is not None)

    def halt(self, reason: str = "", level: str | None = None) -> None:
        """Stop transmitting now, dropping whatever the device still holds:
        Escape, Halt TX, a Stop button. ptt(False) is the normal end, which
        lets the over finish going out. It ends a voice keyer loop too, keyed
        or waiting."""
        self.heartbeat()
        self._keyer_cancel("halted")
        self._unkey(reason, level, "halt")

    def tx_idle(self) -> bool:
        """True when a new over can be keyed now. `keyed` drops the moment
        halt() is called, but the TX thread still has its key-down to do (an
        IC-9700's CAT PTT off takes a serial round trip), and _key refuses
        "Already transmitting" until it has: a caller that halts one over to
        send another in its place (the FT8 panel replacing a queued over
        with the operator's new choice) waits for this rather than for
        `keyed`."""
        with self.lock:
            return not self.st["keyed"] and not (self.tx_thread and self.tx_thread.is_alive())

    # ------------------------------------------------------------ voice keyer
    # Controls whose change means the operator has moved on - tuned, changed
    # mode, gone split - so a CQ loop stops rather than calling again on
    # wherever the dial now is. "A receive-side action cancels it": a click
    # on a scope, a band button, auto-tune and a memory recall all arrive
    # here as one of these.
    KEYER_CANCEL: tuple = ("vfo", "txVfo", "split", "mode", "rit", "ritOn", "xit", "xitOn")

    def send_voice(self, slot: int, _repeat: bool = False) -> None:
        """Send voice memory `slot` (0-based; ohscore/keyer.py) in the current
        voice mode: PTT's own request, keyed through `_key` - so the app's
        transmit guard, its key-up choreography and the same voice chain all
        apply as for the microphone - with the recording read in place of
        the microphone. The over ends by itself when the recording does.
        With keyerRepeat on it goes again keyerRepeatSec after each end,
        until something cancels it (KEYER_CANCEL, ptt, halt, a refusal).
        Raises ValueError (TxRefused when keying is refused)."""
        if not _repeat:
            # The loop's own re-send must not feed the watchdog: a window
            # that has stopped responding must not keep calling CQ.
            self.heartbeat()
            self._keyer_cancel("another memory")
        mode = self.st["mode"]
        if mode not in VOICE_MODES:
            raise ValueError(_("Voice memories send in the voice modes; the radio is in {mode}").format(mode=mode.upper()))
        audio = self.keyer.slots.load(slot)
        secs = len(audio) / AUDIO_RATE
        if secs > self.st["txTimeoutSec"]:
            # Refused before key-up, as send() refuses a long message: half
            # a CQ is no use to anyone.
            raise TxRefused(f"That memory takes {secs:.0f} s to send, longer than the transmit time-out "
                            f"({self.st['txTimeoutSec']:.0f} s, Settings › Transmit & safety)")
        if self.st["keyed"]:
            raise TxRefused("Already transmitting")
        req = self._ptt_req(mode)
        req["source"] = f"voice:{slot + 1}"
        req["memory"] = audio
        label = self.keyer.slots.label(slot)
        # Armed and announced before the key-up: a memory so short that its
        # over ends before _key returns must find the loop there, and must
        # not have its line put back on the card after the over cleared it.
        self.keyer.arm(slot if self.st.get("keyerRepeat") else None)
        self.tx_warn("keyer", f"Sending voice memory {slot + 1}: {label}", "info")
        try:
            self._key(req)
        except ValueError:
            self.keyer.cancel("refused")
            self.tx_clear("keyer")
            raise

    def _keyer_cancel(self, reason: str) -> None:
        if self.keyer.cancel(reason):
            self.tx_clear("keyer")

    def _keyer_over_ended(self, finished: bool) -> None:
        """On the TX thread, after a memory's over: go round again or stop."""
        if self.keyer.over_ended(finished, float(self.st.get("keyerRepeatSec", 10.0))):
            self._keyer_tick(time.monotonic())
        else:
            self.tx_clear("keyer")

    def _keyer_tick(self, now: float) -> None:
        """The supervisor's 10 Hz: a CQ loop's countdown on the transmit card,
        and the next send when it is due."""
        due = self.keyer.due(now)
        if due is None or self.st["keyed"]:
            return
        slot, left = due
        if left > 0:
            shown = math.ceil(left)
            if shown != self.keyer.loop_shown:
                self.keyer.loop_shown = shown
                self.tx_warn("keyer", f"Voice memory {slot + 1} again in {shown} s "
                                      "(PTT, Esc or tuning stops it)", "info")
            return
        # Taken once: the supervisor and the TX thread's end-of-over both
        # come here, and only one of them may send.
        if not self.keyer.claim(slot, now):
            return
        if now - self.last_heartbeat > self.st["watchdogSec"]:
            self._keyer_cancel("watchdog")
            self.toast(_("The voice keyer stopped repeating: the window stopped responding"), "warn")
            return
        try:
            self.send_voice(slot, _repeat=True)
        except ValueError as e:
            # A refusal by _key has already been toasted; anything else
            # (the file gone, the mode changed under it) is said here.
            self._keyer_cancel("refused")
            if not isinstance(e, TxRefused):
                self.toast(_("The voice keyer stopped repeating: {error}").format(error=e), "warn")

    def _release(self) -> None:
        """A normal end asked for from outside the TX thread (PTT released):
        the TX thread stops taking audio and drains. Before RF is up there
        is nothing to drain, and the release is an ordinary unkey - which
        is what cancels an FT8 slot wait or a sequencer's key-up delay."""
        with self.lock:
            if not self.st["keyed"]:
                return
            if self.tx_on_air:
                self.tx_releasing = True
                return
        self._unkey("", None, "released before it went on air")

    def send(self, mode: str, **msg) -> None:
        """Queue a digital transmission rendered by the mode's encoder.
        ft8/ft4 start in the current slot if still within SLOT_LATE of its
        normal start, else the next (msg period="even"/"odd" to choose): see
        slot_start().
        With late_start=True an ft8 over too late for that may still go in
        the current slot, up to SLOT_TRUNCATE into it, with the symbols
        already past dropped (slot_truncate).
        CW without an encoder in ohscore.modes uses the built-in keyer."""
        late_start = bool(msg.pop("late_start", False))
        asked = time.time()
        self.heartbeat()
        over = mode in self.OVER_MODES
        if mode not in self.STATE.modes and not over:
            raise ValueError(_("Unknown mode {mode}").format(mode=repr(mode)))
        if mode != self.st["mode"] and not over:
            raise ValueError(_("Switch to {mode} before sending (the radio is in {current})").format(
                mode=mode, current=self.st["mode"]))
        if mode in modes_glue.RX_ONLY_MODES:
            raise TxRefused(self._rx_only_why(mode))
        if mode == "hsmodem" and not str(self.st.get("callsign") or "").strip():
            # HSmodem identifies the sender in every transmission (its station
            # frame); without a call there is nothing lawful to put there.
            raise TxRefused("Set your callsign (Settings › Station) before sending: HSmodem sends it with every file")
        if mode == "kgstv" and not str(self.st.get("callsign") or "").strip():
            # So does KG-STV (its callsign line), and the program itself
            # refuses to send without one.
            raise TxRefused("Set your callsign (Settings › Station) before sending: KG-STV sends it with every "
                            "picture")
        if mode == "js8" and not str(self.st.get("callsign") or "").strip():
            # JS8 names the sender in its frames (ohscore/modes/js8.py frames).
            raise TxRefused("Set your callsign (Settings › Station) before sending: JS8 sends it with every "
                            "message")
        audio = self._render(mode, msg)
        if audio is None or not len(audio):
            raise ValueError(_("{mode} cannot transmit here: {missing}").format(
                mode=mode, missing=self.modes_info.get(mode, {}).get("missing", "")))
        secs = len(audio) / AUDIO_RATE
        if secs > self.st["txTimeoutSec"]:
            # Refused before key-up rather than cut off by the time-out part
            # of the way through: half a file is no use to the other station.
            raise TxRefused(f"That takes {secs:.0f} s to send, longer than the transmit time-out "
                            f"({self.st['txTimeoutSec']:.0f} s, Settings › Transmit & safety)")
        peak = float(np.max(np.abs(audio)))
        if peak > 1.0:
            audio = audio / peak
        start_at = 0.0
        align = None
        if mode in ("ft8", "ft4", "q65", "js8"):
            # JS8 is one mode with five speeds, each with its own period.
            slot_mode = js8_slot_key(msg.get("speed")) if mode == "js8" else mode
            now = time.time()
            align = slot_truncate(now, slot_mode, msg.get("period"), asked) if late_start else None
            start_at = now if align is not None else slot_start(now, slot_mode, msg.get("period"))
        req = {"source": f"send:{mode}", "mode": mode, "audio": audio.astype(np.float32), "start_at": start_at}
        if align is not None:
            # When the audio would have started had it been on time: the TX
            # thread starts the waveform as far in as the clock has gone past
            # this, measured as the audio starts (after rendering, the slot
            # wait and the key-up, an IC-9700's PTT delay included).
            req["align_t0"] = align
        # For the over's log line only (_log_over_start).
        req["text"] = str(msg.get("text") or msg.get("message") or "")
        req["offset"] = msg.get("offset", msg.get("freq"))
        req["occupied_dial"] = self._tx_dial(self.st)
        req["occupied"] = self._occupied(mode, req["occupied_dial"], req["audio"])
        if self.st["keyed"]:
            raise TxRefused("Already transmitting")
        self._key(req)

    def _render(self, mode: str, msg: dict) -> np.ndarray | None:
        enc = modes_glue.encoder(mode)
        if enc is not None:
            opts = dict(msg)
            if mode == "cw":
                opts.setdefault("wpm", self.st["cwWpm"])
                opts.setdefault("freq", self.st["cwPitch"])
            if mode == "hsmodem":
                # The speed is the receiver's too (hsSpeed), and the station
                # frame carries the operator's call and locator.
                opts.setdefault("speed", int(self.st.get("hsSpeed") or 4410))
                opts.setdefault("callsign", self.st.get("callsign", ""))
                opts.setdefault("locator", self.st.get("locator", ""))
            if mode in ("kgstv", "js8"):
                # KG-STV's callsign line and JS8's sender are the station's
                # own, always: a caller cannot send a picture or a JS8
                # message under somebody else's call.
                opts["callsign"] = self.st.get("callsign", "")
                opts["locator"] = self.st.get("locator", "")
            return np.asarray(enc.render(**opts), np.float32)
        if mode == "cw" and msg.get("text"):
            env = morse.envelope(str(msg["text"]), float(msg.get("wpm", self.st["cwWpm"])), AUDIO_RATE, tail=0.1)
            t = np.arange(len(env)) / AUDIO_RATE
            return (0.9 * env * np.sin(2 * np.pi * self.st["cwPitch"] * t)).astype(np.float32)
        return None

    def _key(self, req: dict):
        # Every key-up comes through here: a hold that gives way (a band
        # scan) gives the receiver back, and the dial with it, before the
        # guard judges the over.
        self.client_activity("transmit")
        with self.lock:
            why = self._tx_blocked(req.get("occupied"), req)
            if why:
                self._status(txBlocked=why)
                self.toast(_("Not transmitting: {why}").format(why=why), "warn")
                raise TxRefused(why)
            if self.st["keyed"] or (self.tx_thread and self.tx_thread.is_alive()):
                raise TxRefused("Already transmitting")
            self.tx_req = req
            self.tx_end = ""
            self.tx_halt.clear()
            self.tx_releasing = False
            self.tx_on_air = False
            # The supervisor times the over from tx_t0 as soon as keyed is
            # set, but the TX thread only stamps it after key-up (and, for
            # FT8, after waiting for the slot). Until then it held the start
            # of the previous over - 0.0 on the first - so a supervisor tick
            # in that gap saw an over hundreds of seconds old and unkeyed it
            # at once with "transmit time-out". Stamp both clocks here; the
            # TX thread restamps them when it actually starts sending.
            self.tx_t0 = self.last_mic_audio = time.monotonic()
            self.st["keyed"] = True
            self.pending["keyed"] = True
            # keyed covers the slot wait too (an FT8 panel queues its over
            # 2.5 s into the slot before), so an on-air light that followed
            # it showed ON AIR through the receive slot (Ray, 12/10/2026).
            # txOnAir is the over actually up; txStartAt says when it will be.
            for k, v in (("txOnAir", False), ("txStartAt", float(req.get("start_at") or 0.0))):
                if self.st.get(k) != v:
                    self.st[k] = self.pending[k] = v
        # An over whose audio goes to another radio's sound card (NB's
        # IC-9700 by CAT PTT): the card is opened here, before the TX
        # thread exists and outside the lock, so a device that is missing
        # refuses the over to its caller, as a guard refusal does, rather
        # than failing silently on the thread later.
        try:
            req["sink"] = self._tx_audio_out(req)
        except ValueError as e:
            with self.lock:
                self.st["keyed"] = False
                self.pending["keyed"] = False
            self._status(txBlocked=str(e), txStartAt=0.0)
            self.toast(_("Not transmitting: {why}").format(why=e), "warn")
            raise TxRefused(str(e)) from None
        # A voice memory being recorded or previewed gives the microphone
        # and the monitor to the transmitter (ohscore/keyer.py).
        self.keyer.yield_audio()
        self.tx_thread = threading.Thread(target=self._tx_loop, args=(req,), name=f"{self.THREAD_PREFIX}-tx",
                                          daemon=True)
        self.tx_thread.start()

    def _unkey(self, reason: str, level: str | None, why: str = ""):
        """The emergency unkey (module docstring): RF stops at once and the
        device's queue is dropped, even part-way through a drain. `why` is
        the over's ending for its log line (_log_over_end): halt, timeout,
        watchdog, link lost..., the first one given winning."""
        with self.lock:
            was = self.st["keyed"]
            self.st["keyed"] = False
            self.tx_halt.set()
            if was:
                self.pending["keyed"] = False
                if not getattr(self, "tx_end", ""):
                    self.tx_end = why or ("unkeyed: " + reason.removeprefix("Unkeyed: ") if reason else "unkeyed")
        if was and reason:
            self.toast(reason, level or "info")
            if level in ("warn", "error"):
                # An over the operator did not end: a fault for the
                # opt-in diagnostics upload (ohscore/diagupload.py).
                diag.notable("over-aborted", reason)

    def _tx_loop(self, req: dict):
        s = self.st
        dev = self.dev
        n = self.BLOCK_HOPS * (self.geo.L // self.geo.decimation_for(AUDIO_RATE))   # 12 kHz samples per block
        mode = req["mode"]
        voice = self._voice_over(req)
        audio = req.get("audio")
        memory = req.get("memory")
        # Speech from the sound card's microphone (a voice memory brings
        # its own): opened for this over and closed after it, never at
        # start-up (ohscore/audio.py says why).
        mic = voice and memory is None
        mic_held = False
        pos = 0
        finished = False
        sink = req.get("sink")
        on_air_at = None
        failed = ""
        under0 = self._tx_underruns(dev, sink)
        try:
            if req.get("start_at"):
                # Keyed `lead` early, so that a transmitter that must be
                # keyed some time before its audio (NB's IC-9700: PA and
                # upconverter switching) still starts the audio on time.
                at = req["start_at"] - self._tx_key_lead(req)
                while time.time() < at and s["keyed"] and not self.stop_ev.is_set():
                    time.sleep(min(0.05, max(0.0, at - time.time())))
                if not s["keyed"]:
                    return
            sideband = "lsb" if mode == "lsb" else "usb"
            stream = req.get("stream")
            pending = np.zeros(0, np.float32)
            if voice and stream is None:
                self.mod.configure(s["txFilterLo"], s["txFilterHi"], s["micGain"], s["compressor"], True, sideband)
            else:
                self.mod.configure(100.0, 2950.0, 0.0, 0.0, False, "usb")
            mod, src = self._tx_chain(req)
            if mic:
                # Before the key-up, so an open that is slow - or waiting
                # on the system's permission prompt - holds back the
                # carrier, not the audio on it; a PTT let go meanwhile
                # never keys at all.
                note = self.audio.open_mic()
                mic_held = True
                if note:
                    self.toast(note, "warn")
                if not s["keyed"]:
                    return
            t_key = time.time()
            self._tx_key_up(dev)
            if req.get("align_t0") and audio is not None:
                # A late start (slot_truncate): the waveform from where a
                # punctual over would be by now; the symbols already past
                # are dropped. Never past the end - that would send nothing.
                pos = min(len(audio), max(0, int(round((time.time() - req["align_t0"]) * AUDIO_RATE))))
                req["skipped_s"] = pos / AUDIO_RATE
            with self.lock:
                self.tx_on_air = True
            self.tx_t0 = on_air_at = time.monotonic()
            self._log_over_start(req, t_key, time.time())
            self.last_mic_audio = time.monotonic()
            self._status(txSource=req["source"], txSeconds=0.0, txBlocked="", txOnAir=True, **self._on_keyed())
            phase = 0.0
            while s["keyed"] and not self.tx_releasing and not self.stop_ev.is_set():
                if voice:
                    if memory is not None:
                        # A voice memory: the recording where the microphone
                        # would be, and everything after it the same.
                        a = memory[pos:pos + n]
                        pos += n
                        if len(a) == 0:
                            finished = True
                            break
                        if len(a) < n:
                            a = np.concatenate([a, np.zeros(n - len(a), np.float32)])
                        self.mic_level = float(20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-9))
                    else:
                        a = self.audio.read_mic(n)
                        self.mic_level = float(self.audio.mic_level())
                    if np.sqrt(np.mean(a ** 2)) > 10 ** (-50 / 20):
                        self.last_mic_audio = time.monotonic()
                    if stream is not None:
                        # Digital voice: speech in, modem audio out, in the
                        # codec's own frame sizes - buffered to our blocks.
                        speech = a * np.float32(10 ** (s["micGain"] / 20))
                        pending = np.concatenate([pending, np.asarray(stream.process(speech), np.float32)])
                        a, pending = pending[:n], pending[n:]
                        if len(a) < n:
                            a = np.concatenate([a, np.zeros(n - len(a), np.float32)])
                elif audio is not None:
                    a = audio[pos:pos + n]
                    pos += n
                    if len(a) < n:
                        if len(a) == 0:
                            break
                        a = np.concatenate([a, np.zeros(n - len(a), np.float32)])
                else:
                    # CW key-down / tune: a steady tone at the pitch (continuous phase).
                    w = 2 * np.pi * s["cwPitch"] / AUDIO_RATE
                    a = (0.9 * np.sin(phase + w * np.arange(n))).astype(np.float32)
                    phase = (phase + w * n) % (2 * np.pi)
                if sink is not None:
                    # Audio for another radio's modulator: no SSB
                    # modulator, no IQ, the SDR untouched. The follow
                    # hook still runs every block - it is where the app
                    # checks that radio is still there and still keyed.
                    if s["monitor"]:
                        self.audio.monitor(a * np.float32(s["monitorLevel"]))
                    if not self._tx_follow(dev):
                        break
                    # What that radio's SSB modulator will make of it,
                    # for the app to find its own signal by (NB's TX
                    # lock on the IC-9700). Before the write, so the
                    # sink's queue still says when this block plays.
                    self._tx_sent(dev, mod(a))
                    sink.write(a)
                    continue
                bb = mod(a)
                self.tx_peak = mod.last_peak
                if s["monitor"]:
                    self.audio.monitor(a * np.float32(s["monitorLevel"]))
                if not self._tx_follow(dev):
                    break
                iq = self.synth.render(self.BLOCK_HOPS, [(src, bb)])
                if self.tx_invert:
                    iq = np.conj(iq)
                self._tx_sent(dev, bb)
                dev.write(iq)
            if sink is not None:
                if not self._tx_halted():
                    self._tx_drain(sink)
            elif not self._tx_halted():
                # One frame of silence through the synthesis, not straight to
                # the device: it carries out the last 2.5 ms the synthesis
                # filter still holds, and the device's own resampler's.
                tail = self.synth.render(1, [(src, np.zeros(src.hop, np.complex64))])
                dev.write(np.conj(tail) if self.tx_invert else tail)
                self._tx_drain(dev)
            finished = finished and not self._tx_halted()
        except Exception as e:  # noqa: BLE001 - any failure ends the over, safely
            failed = f"error: {e}"
            self.log.exception("tx failed")
            diag.notable("over-failed", str(e))
            self.toast(_("Transmit stopped: {error}").format(error=e), "error")
        finally:
            if mic_held:
                self.audio.close_mic()
            if req.get("stream") is not None and hasattr(req["stream"], "close"):
                try:
                    req["stream"].close()
                except Exception:  # noqa: BLE001
                    pass
            with self.lock:
                self.st["keyed"] = False
                self.pending["keyed"] = False
                self.tx_on_air = False
                self.tx_releasing = False
            if sink is not None:
                # The audio stops before the transmitter is unkeyed
                # (_tx_key_down), never after.
                try:
                    sink.tx_stop()
                except Exception:  # noqa: BLE001
                    pass
            try:
                self._tx_key_down(dev)
            except Exception:  # noqa: BLE001
                pass
            self._log_over_end(req, on_air_at, failed, under0, self._tx_underruns(dev, sink))
            extra = self._on_unkeyed()
            self.tx_peak = 0.0
            self.tx_req = None
            self._status(txSource="", txOnAir=False, txStartAt=0.0, **extra)
            if memory is not None:
                self._keyer_over_ended(finished)

    # ----------------------------------------------------------- over log
    # One line as each over goes on air and one as it ends, so a log alone
    # says what was sent, when against its slot, through what, and why it
    # stopped (Ray's IC-9700 by CAT PTT, 12/10/2026: until then the log
    # had "keyed by CAT" and "unkeyed by CAT" and nothing between).
    END_QUIET = ("normal", "halt", "released before it went on air", "radio stopped")

    def _log_over_start(self, req: dict, t_key: float, t_audio: float) -> None:
        parts = [req["mode"]]
        if req.get("text"):
            parts.append(repr(req["text"]))
        if req.get("offset") is not None:
            parts.append(f"at {float(req['offset']):.0f} Hz")
        parts.append(f"({req['source']})")
        line = " ".join(parts)
        if req.get("start_at"):
            # Against the slot: FT8 wants audio 0.5 s in, WSJT-X's
            # tolerance is about +-1 s, so this is the first thing to read
            # when nobody hears an over.
            line += (f"; keyed at slot {t_key - req['start_at']:+.2f} s, audio from slot "
                     f"{t_audio - req['start_at']:+.2f} s")
        if req.get("align_t0"):
            line += (f"; late start, aligned to the slot: the first {req.get('skipped_s', 0.0):.2f} s of the "
                     f"message dropped")
        facts = self._over_facts(req)
        self.log.info("over start: %s%s", line, f"; {facts}" if facts else "")

    def _log_over_end(self, req: dict, on_air_at: float | None, failed: str, under0, under1) -> None:
        ended = failed or getattr(self, "tx_end", "") or ("halt" if self._tx_halted() else "normal")
        dur = f"after {time.monotonic() - on_air_at:.1f} s on air" if on_air_at is not None else "never on air"
        under = ""
        if under1 is not None:
            under = f", TX audio underruns {under1 - (under0 or 0)}"
        level = logging.INFO if ended in self.END_QUIET else logging.WARNING
        self.log.log(level, "over end: %s %s, ended %s%s", req["mode"], dur, ended, under)

    @staticmethod
    def _tx_underruns(dev, sink) -> int | None:
        """The over's audio underrun count so far: the external radio's
        sound device's (TxOut.underruns), or the SDR's own (txUnderruns in
        its status) - None where neither keeps one."""
        if sink is not None:
            return getattr(sink, "underruns", None)
        try:
            n = (dev.status() or {}).get("txUnderruns") if dev is not None else None
        except Exception:  # noqa: BLE001 - a status read must not end an over
            return None
        return int(n) if isinstance(n, (int, float)) else None

    def _over_facts(self, req: dict) -> str:
        """The app's part of the over-start line: what transmits it and how
        (NB: the IC-9700's sound device, level and PTT delay)."""
        return f"device {self.cfg.get('device')}"

    def _tx_halted(self) -> bool:
        return self.tx_halt.is_set() or self.stop_ev.is_set()

    def _tx_drain(self, dev) -> None:
        """A normal end: let the device send what it holds, RF still on and
        `keyed` still true, so the last of the over reaches the air before
        _tx_key_down. Up to NB 0.1.5 and HAM 0.1.6 the engine wrote 15 ms
        of silence and called tx_stop at once, which empties the queue: the
        simulator's ~225 ms, the Pluto's ring, the HL2's 40 ms - the last
        CW element, the last characters of RTTY or PSK, a voice over's last
        syllable. (HAM drained the HL2 itself, but on Escape and the
        watchdog too.)
        Bounded (DRAIN_SLACK, DRAIN_MAX), and abandoned the moment an
        emergency unkey comes in."""
        dev.tx_finish()
        t0 = time.monotonic()
        left = dev.tx_queued()
        deadline = t0 + min(self.DRAIN_MAX, left + self.DRAIN_SLACK)
        block = self.BLOCK_HOPS * self.geo.L / self.geo.fs
        check = t0 + block
        while not self._tx_halted():
            left = dev.tx_queued()
            if left <= 0:
                self.log.debug("tx queue drained in %.0f ms", 1000 * (time.monotonic() - t0))
                return
            now = time.monotonic()
            if now >= deadline:
                self.log.warning("the %s still held %.0f ms of transmit after %.0f ms: stopping it anyway",
                                 self.cfg.get("device"), 1000 * left, 1000 * (now - t0))
                return
            if now >= check:
                # The app's protections, at the cadence they see while keyed.
                check += block
                if not self._tx_draining(dev):
                    return
            time.sleep(min(0.01, left))

    def _tx_draining(self, dev) -> bool:
        """Every block's time while a normal end drains: what _tx_follow's
        protections would check. False ends it (the hook unkeys, saying why)."""
        return True

    def _tx_chain(self, req: dict):
        """(modulator, Source) for this over: the modulator turns each block
        of 12 kHz audio into baseband (and has `last_peak`); the Source places
        that baseband at its rate. Default: the SSB modulator at 12 kHz."""
        return self.mod, self.tx_src

    def _tx_audio_out(self, req: dict):
        """For an over whose audio goes to another radio's sound card rather
        than through this engine's SDR: an open ohscore.audio.TxOut, which
        the transmit loop then writes the 12 kHz audio to (no modulator, no
        IQ), drains on a normal end and stops before `_tx_key_down`. None
        (the default): the SDR transmits. Raises ValueError (a sentence) to
        refuse the over. Called from _key, after the guard has passed."""
        return None

    def _tx_key_lead(self, req: dict) -> float:
        """Seconds before a timed over's start (`start_at`) to call
        _tx_key_up, for a transmitter that must be keyed some time before
        its audio starts. Default 0."""
        return 0.0

    def _tx_key_up(self, dev) -> None:
        """Tune the transmitter for the current dial, set its power and start
        it: the app's key-up choreography."""
        raise NotImplementedError

    def _tx_follow(self, dev) -> bool:
        """Each block while keyed: follow the dial (phase-continuous). False
        ends the over (the hook unkeys, saying why)."""
        return True

    def _tx_sent(self, dev, bb: np.ndarray) -> None:
        """Each block while keyed, just before it is written: the baseband
        about to go out. For an over to another radio's sound card
        (`_tx_audio_out`) too: then `bb` is the USB baseband the engine's
        modulator makes of the audio - what that radio sends relative to
        its dial - and the SDR is not involved (`self.tx_req["sink"]`
        says when the block will play)."""

    def _tx_key_down(self, dev) -> None:
        """Stop the transmitter: the app's key-down choreography."""
        dev.tx_stop()

    def _on_keyed(self) -> dict:
        """On the TX thread once transmitting: status to publish with it."""
        return {}

    def _on_unkeyed(self) -> dict:
        """On the TX thread once stopped: status to publish with it."""
        return {}

    # ---------------------------------------------------------------- supervisor
    def _supervise(self):
        while not self.stop_ev.wait(0.1):
            now = time.monotonic()
            s = self.st
            if s["keyed"]:
                secs = now - self.tx_t0
                self._status(txSeconds=round(secs, 1))
                activity = max(self.last_heartbeat, max((f.last_drain for fl in self.feeds.values() for f in fl),
                                                        default=0.0))
                if secs > s["txTimeoutSec"]:
                    self._unkey(f"Unkeyed: transmit time-out ({s['txTimeoutSec']:.0f} s)", "warn", "timeout")
                elif (self.tx_req and self.tx_req["source"] == "ptt" and s["mode"] not in ("cw",)
                      and now - self.last_mic_audio > s["deadAirSec"] and secs > s["deadAirSec"]):
                    self._unkey(f"Unkeyed: no microphone audio for {s['deadAirSec']:.0f} s", "warn", "dead air")
                elif now - activity > s["watchdogSec"]:
                    self._unkey("Unkeyed: the user interface stopped responding (watchdog)", "error", "watchdog")
            self._status(cpu=round(getattr(self, "cpu", 0.0), 3), cpuWait=round(getattr(self, "cpu_wait", 0.0), 3),
                         deviceStatus=self._device_status(),
                         audio=self.audio.status() if self.audio else {}, overruns=self.overruns,
                         rxLate=self.rx_late, rxLostS=round(self.rx_lost / self.geo.fs, 3),
                         rxBehindS=round(self.prefetch.behind_s, 3) if self.prefetch is not None else 0.0,
                         rxStreamPct=self._stream_pct(now), **self._supervise_status())
            self.decoders.tick()
            self._keyer_tick(now)
            self._diag_tick(now)
            self._rec_tick()
            self._play_tick()
            self._app_tick(now)
            with self.lock:
                changes, self.pending = self.pending, {}
            if changes:
                if any(k in changes for k in self.DERIVE_ON):
                    self._derive()
                    with self.lock:
                        changes.update(self.pending)
                        self.pending = {}
                self._publish("state", {"t": time.time(), "changes": changes})
            self._save()

    def _device_status(self) -> dict:
        """The device's status with its gain sense (Device.gain_sense) in
        it, which the S-meter's calibration reads from here. A stand-in
        device that is not a Device subclass simply has none."""
        if not self.dev:
            return {}
        sense = getattr(self.dev, "gain_sense", None)
        return {**(sense() if sense is not None else {}), **self.dev.status()}

    # rxStreamPct's window: long enough that one lost block is not a
    # headline (75 ms of 10 s is under 1 %), short enough that a link that
    # starts starving shows within seconds.
    STREAM_WINDOW_S = 10.0

    def _stream_pct(self, now: float) -> float:
        """How much of the radio's stream reached the program over the last
        STREAM_WINDOW_S, percent: samples received against received plus
        lost (rx_lost: ohscore/rxprefetch.py tells from the radio's own
        clock when samples never arrived). 100 when nothing is known to be
        missing - a device read without the prefetch reader cannot tell.

        Why (Windows test 17/10/2026, finding 1): over a Tailscale relay a
        PC got 37 % of the Pluto's samples, and the status bar went on
        saying "1.2 MS/s" - the rate the radio was set to, not what
        arrived. The window shows this instead when it is short."""
        h = self.stream_hist
        if h and self.rx_samples < h[-1][1]:
            h.clear()                       # a restart: the counts began again
        h.append((now, self.rx_samples, self.rx_lost))
        while len(h) > 2 and now - h[1][0] >= self.STREAM_WINDOW_S:
            h.popleft()
        got = h[-1][1] - h[0][1]
        lost = h[-1][2] - h[0][2]
        if got + lost <= 0:
            return 100.0
        return round(100.0 * got / (got + lost), 1)

    def _supervise_status(self) -> dict:
        """Status the supervisor republishes ten times a second."""
        return {}

    def _app_tick(self, now: float) -> None:
        """The app's own work on the supervisor, ten times a second while
        the radio runs (Radio: the nightly band scan)."""

    # ------------------------------------------------------------- recording
    def recordings_dir(self) -> Path:
        return host.recordings_dir(self.data_dir)

    def start_recording(self, limit_s: float | None = None, folder: Path | None = None) -> Path:
        """Record the receive IQ to a SigMF pair in `folder` (default
        recordings_dir(); ohscore/sigmf.py) until stop_recording(), the
        radio stops, or `limit_s` seconds (default: the recLimitMin
        setting; 0 is no limit). Returns the .sigmf-data path. Raises
        ValueError with a sentence: not running, already recording, or the
        folder cannot be written. Never touches the transmitter."""
        # Recording what is heard: a band scan gives the receiver back first.
        self.client_activity("recording")
        with self.lock:
            if not self.running:
                raise ValueError(_("Start the radio before recording"))
            if self.rec is not None:
                raise ValueError(_("Already recording"))
            if self.play is not None:
                raise ValueError(_("This is a recording already: go back to the radio to record"))
        s = self.state()
        if limit_s is None:
            limit_s = float(s.get("recLimitMin") or 0.0) * 60.0
        folder = Path(folder) if folder is not None else self.recordings_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            station = self.broadcast_station()
            mode = station["mode"] if station else s["mode"]
            base = sigmf.new_base(folder, self.CONFIG.app.name, time.time(), s["rxDial"], mode, station)
            rec = sigmf.Recorder(base, self.geo.fs, self._rec_meta(s, station), limit_s or None).start()
        except OSError as e:
            raise ValueError(_("Could not record to {folder}: {error}").format(folder=folder, error=e)) from e
        with self.lock:
            self.rec = rec
        self._status(recording=True, recFile=str(rec.data_path), recSeconds=0.0, recBytes=0, recDropped=0,
                     recRxLost=0)
        self.log.info("recording to %s (%s)", rec.data_path,
                      f"limit {limit_s:g} s" if limit_s else "no time limit")
        return rec.data_path

    def stop_recording(self) -> Path | None:
        """End the recording, if there is one; returns its .sigmf-data path.
        The writer finishes on its own thread; a toast says when it is saved."""
        rec = self.rec
        if rec is None:
            return None
        self._rec_end(rec, "")
        return rec.data_path

    def _rec_end(self, rec, reason: str) -> None:
        with self.lock:
            if self.rec is rec:
                self.rec = None
            if rec not in self.rec_closing:
                self.rec_closing.append(rec)
        rec.close(reason)
        self._status(recording=False)

    def _rec_push(self, rec, x: np.ndarray) -> None:
        """The receive thread's part: hand the block over, never wait."""
        s = self.st
        dev = self.dev
        pf = self.prefetch
        gap = 0
        if pf is not None and pf.utc is not None:
            # Read ahead (ohscore/rxprefetch.py): when the block arrived, not
            # when it was processed - from a queue that has fallen behind
            # the wall clock would mark a gap that is not there - and the
            # samples the stream lost just before it.
            utc, gap = pf.utc, pf.gap
        elif getattr(dev, "own_clock", False):
            utc = dev.utc_end - len(x) / self.geo.fs
        elif getattr(dev, "realtime", True) is False and hasattr(dev, "t_epoch"):
            utc = dev.t_epoch + (self.rx_samples - len(x)) / self.geo.fs
        else:
            # A real device delivers in real time: the block just read began
            # its length ago. Only captures carry a time, so a few ms of
            # scheduling jitter here cannot accumulate.
            utc = time.time() - len(x) / self.geo.fs
        facts = {"keyed": bool(s.get("keyed"))}
        for k in self.REC_STATES:
            facts[k] = s.get(k)
        track = {k: s.get(k) for k in self.REC_TRACK} if self.REC_TRACK else None
        if not rec.push(x, self._rec_centre(), utc, facts, track, rx_gap=gap):
            self._rec_end(rec, rec.reason)

    def _rec_tick(self) -> None:
        """On the supervisor: the recording's progress as status, and a
        toast for each recording whose writer has finished."""
        rec = self.rec
        if rec is not None:
            self._status(recSeconds=round(rec.seconds, 1), recBytes=int(rec.nbytes), recDropped=int(rec.dropped),
                         recRxLost=int(rec.rx_lost))
        for r in list(self.rec_closing):
            if not r.done.is_set():
                continue
            self._status(recSeconds=round(r.seconds, 1), recBytes=int(r.nbytes), recDropped=int(r.dropped),
                         recRxLost=int(r.rx_lost))
            m, sec = divmod(int(round(r.written / r.fs)), 60)
            took = (_("{m} min {s:02d} s").format(m=m, s=sec) if m else _("{s} s").format(s=sec))
            # The dropped-samples sentence is whole and stands after the
            # main one; with a reason and without are two sentences, and
            # "time limit" (sigmf's word for why it ended) is translated
            # as the label it is.
            # Which loss, said apart: the disk's (the writer fell behind) or
            # the receive stream's (the samples never reached the program -
            # the link to the radio). One sentence was all there was until
            # 17/10/2026, and it blamed the disk for a stalled network.
            lost = (" " + _("{seconds:.1f} s of samples were dropped because the disk could not keep up "
                            "(the file says where).").format(seconds=r.dropped / r.fs) if r.dropped else "")
            if r.rx_lost:
                lost += " " + _("{seconds:.1f} s of samples never arrived from the radio: its stream had gaps, "
                                "usually the link to it (network or USB) stalling (the file says where)."
                                ).format(seconds=r.rx_lost / r.fs)
            if r.error:
                self.toast(_("{error}. {took} were saved as {file}.").format(
                    error=r.error, took=took, file=r.data_path.name) + lost, "error")
                self.rec_closing.remove(r)
                continue
            reason = _("time limit") if r.reason == "time limit" else r.reason
            msg = (_("Recording saved ({reason}): {name}, {took}, {size}. Send both files, .sigmf-data and .sigmf-meta.")
                   if r.reason else
                   _("Recording saved: {name}, {took}, {size}. Send both files, .sigmf-data and .sigmf-meta."))
            self.toast(msg.format(reason=reason, name=r.data_path.stem, took=took, size=sigmf.size_text(r.nbytes))
                       + lost, "warn" if r.dropped or r.rx_lost else "info")
            # Off the list only once the operator has been told: whatever
            # waits for rec_closing to empty (a test, or anything that says
            # "saved" after it) must find the toast already published. It
            # was removed first until 22/10/2026, and a supervisor
            # preempted between the two let a loaded test runner see the
            # list empty and no toast yet.
            self.rec_closing.remove(r)
            self.log.info("recording %s saved: %d samples, %d dropped, %d clipped", r.data_path, r.written,
                          r.dropped, r.clipped)

    def _rec_centre(self) -> tuple[float, float]:
        """(device Hz, on-air Hz) of the IQ stream's DC, as the hardware is
        tuned: a recording starts a new capture when either changes, so
        an app must not return something that moves every block (NB's
        corrected dial does: it reports the LNB's nominal instead)."""
        return float(self.rx_if), float(self._dial_at(0.0))

    def _rec_extra(self, s: dict) -> dict:
        """The app's own fields for a recording's metadata, without the
        `openhamshack:` prefix (NB: the LNB, rxCorr and beacon lock)."""
        return {}

    def broadcast_station(self) -> dict | None:
        """The broadcast station being heard now, for a recording's
        metadata and name (host.recording_name): Radio's DAB station while
        a DAB session holds the receiver, or the wide FM station and its
        RDS (ohsradio/radio.py, which says what is in it). None while
        there is none, and always in an app with no broadcast reception
        (QO-100 NB)."""
        return None

    def _rec_meta(self, s: dict, station: dict | None = None) -> dict:
        """A recording's global metadata (ohscore/sigmf.py adds the format's
        own fields): enough to analyse it without asking whoever sent it.
        `station` is broadcast_station() as the recording started."""
        dev = self.dev
        try:
            dst = dict(dev.status()) if dev is not None else {}
        except Exception as e:  # noqa: BLE001 - a status that fails must not stop a recording
            dst = {"status": f"unavailable ({e})"}
        # Never the radio's serial number: a recording is meant to be sent
        # to other people, and nothing in it needs to say which unit.
        dst = {k: v for k, v in dst.items() if "serial" not in k.lower()}
        ctx = {k: v for k, v in self.device_context().items() if "serial" not in k.lower()}
        version = diag.app_version(self.APP_PACKAGE) if self.APP_PACKAGE else ""
        app = f"{self.APP_NAME or self.CONFIG.app.name} {version}".strip()
        kind = dst.get("kind") or self.cfg.get("device", "")
        model = dst.get("model") or ctx.get("hw_model", "")
        fw = dst.get("fwVersion") or ctx.get("fw_version", "")
        hw = ", ".join(p for p in (f"{kind} {model}".strip(), f"firmware {fw}" if fw else "",
                                   f"FIR {dst['fir']}" if dst.get("fir") else "") if p)
        os_name = diag._os_name()
        receive = {k: s.get(k) for k in ("vfo", "rxDial", "mode", "filterLo", "filterHi", "rit", "ritOn", "agc", "nb",
                                         "nr", "cwPitch", "freedvMode")}
        what = f"{s['rxDial'] / 1e6:.6f} MHz {str(s['mode']).upper()}"
        if station:
            # While DAB holds the receiver the mode in the state is the
            # operator's from before (put back when DAB stops), and nothing
            # demodulates it: an 11B capture was listed as "AM". The mode
            # recorded is what was being received; playing the file back
            # seeds only a mode the radio has (_play_apply refuses "dab"),
            # so the operator's own mode stays.
            receive["mode"] = station["mode"].lower()
            what = f"{s['rxDial'] / 1e6:.6f} MHz {station['mode']}" + (f", {station['label']}" if station.get("label") else "")
        g = {"core:recorder": app, "core:hw": hw,
             "core:description": f"Receive IQ recorded by {app} on {os_name}: {what}",
             "openhamshack:app": self.APP_NAME or self.CONFIG.app.name, "openhamshack:version": version,
             "openhamshack:os": os_name, "openhamshack:start_utc": sigmf.iso_utc(time.time()),
             "openhamshack:receive": receive,
             "openhamshack:gain": {"mode": s.get("rxGainMode"), "db": s.get("rxGain")},
             "openhamshack:inverted": bool(self.rx_invert),
             "openhamshack:device": dst, "openhamshack:device_context": ctx,
             "openhamshack:overruns": int(self.overruns)}
        if s.get("callsign"):
            g["core:author"] = s["callsign"]
            g["openhamshack:callsign"] = s["callsign"]
        if station:
            g["openhamshack:broadcast"] = dict(station)
        for k, v in self._rec_extra(s).items():
            g[f"openhamshack:{k}"] = v
        return g

    # ---------------------------------------------------------------- playback
    # A recording plays through a device of its own (ohscore/devices/
    # filedev.py, whose docstring has the decisions), standing in for the
    # radio behind the same interface. What the engine does about it is
    # only what cannot be the device's: choosing it over the configured
    # radio (start), its clock (_audio_utc), the settings the recording
    # takes over (PLAY_KEYS) and the playing position as status.
    def start_playback(self, path, loop: bool | None = None, realtime: bool = True) -> Path:
        """Play the SigMF recording at `path` (either file of the pair)
        through the receiver instead of the radio, until stop_playback():
        the radio is stopped and the recording started in its place,
        receive-only. `loop` sets playLoop; `realtime=False` plays as fast
        as receive can take it (tests, analysis). The recording seeds the
        dial and mode it was made on, and the app's own values
        (_play_seed); those keys are the operator's again afterwards and
        are never saved meanwhile. Returns the .sigmf-data path. Raises
        ValueError with a sentence: a recording in progress, a file that
        cannot be played, or one that does not start - and then the radio
        is as it was."""
        if self.rec is not None:
            raise ValueError(_("Stop recording before playing a recording"))
        self.client_activity("playback")
        dev = self._play_device(Path(path), realtime)
        if loop is not None:
            self.set(playLoop=bool(loop))
        dev.loop = bool(self.st["playLoop"])
        was = self.running or self.play is not None
        self.stop()
        if self.play_saved is not None:
            # One recording after another: each starts from the operator's values.
            self._play_restore(keep=True)
        else:
            with self.lock:
                self.play_saved = {k: self.st[k] for k in self.PLAY_KEYS}
        self._play_apply(self._play_seed(dev.meta))
        self.play, self.play_said_end = dev, False
        self._status(playing=True, playFile=str(dev.data_path), playPos=0.0, playLength=round(dev.length_s, 1),
                     playUtc=round(dev.recorded_utc(), 1), playEnded=False)
        try:
            self.start()
        except DeviceError as e:
            self.play = None
            self._play_restore()
            self._status(playing=False, playFile="")
            if was:
                try:
                    self.start()
                except DeviceError:
                    pass             # start() has said why, as status and a toast
            raise ValueError(_("{name} cannot be played: {error}").format(name=dev.name, error=e)) from e
        when = time.strftime("%d/%m/%Y %H:%M:%S UTC", time.gmtime(dev.recorded_utc()))
        self.log.info("playing %s (%.0f s at %g S/s, recorded %s)", dev.data_path, dev.length_s, dev.fs, when)
        self.toast(_("Playing {name}, recorded {when}. Transmit is off until you go back to the radio.").format(
            name=dev.name, when=when), "info")
        return dev.data_path

    def stop_playback(self) -> None:
        """Back to the radio: the recording stops, the settings it took over
        are the operator's again, and the configured device starts (raises
        DeviceError as start() does when it cannot be opened)."""
        if self.play is None:
            return
        self.stop()
        self.play = None
        self._play_restore()
        self._status(playing=False, playEnded=False)
        self.log.info("playback stopped; back to the %s", self.cfg.get("device"))
        self.start()

    def _play_device(self, path: Path, realtime: bool):
        """The device that plays `path`; ValueError with a sentence if it cannot."""
        from .devices.filedev import FileDevice
        return FileDevice(path, realtime=realtime)

    def _play_converter(self):
        """The converter the receiver works through, for the recording to be
        heard through on the air (None: directly). An app whose converter
        changes while running (HAM, by band) tells the device itself."""
        return None

    def _play_seed(self, meta: dict) -> dict:
        """State a recording sets when it starts playing, from its metadata
        (all keys in PLAY_KEYS): the dial and mode it was recorded on."""
        rx = meta["global"].get("openhamshack:receive") or {}
        return {k: rx[k] for k in ("vfo", "mode") if k in rx}

    def _play_apply(self, changes: dict) -> None:
        """Set state directly (not through set(): these are the recording's
        values, not the operator's, and set() would say otherwise - NB marks
        an rxCorr from set() as set by hand). A value the registry refuses is
        left as it was."""
        spec = self.STATE.spec
        with self.lock:
            for k, v in changes.items():
                try:
                    v = self.STATE.coerce(k, v)
                except ValueError:
                    continue
                self.st[k] = v
                if spec[k]["persist"]:
                    self.cfg[k] = v
                self.pending[k] = v
            self.reconf = True
        self._derive()

    def _play_restore(self, keep: bool = False) -> None:
        """The operator's own values of PLAY_KEYS back (kept for another
        recording with `keep`)."""
        saved = self.play_saved
        if saved is None:
            return
        self._play_apply(saved)
        if not keep:
            self.play_saved = None

    def _play_tick(self) -> None:
        """On the supervisor: the playing position as status, and one toast
        when the recording has played to its end."""
        dev = self.play
        if dev is None or self.dev is not dev:
            return
        self._status(playPos=round(dev.pos / dev.fs, 1), playUtc=round(dev.recorded_utc(), 1), playEnded=dev.ended)
        if dev.ended and not self.play_said_end:
            self.play_said_end = True
            self.toast(_("{name} has played to its end. File › Back to the radio, or Loop playback to hear it "
                         "again.").format(name=dev.name), "info")
        elif not dev.ended:
            self.play_said_end = False

    # ---------------------------------------------------------------- diagnostics
    def _diag_tick(self, now: float) -> None:
        """On the supervisor, never the receive thread: log what changed
        (ohscore/diag.py Watch) and keep a status line a second for a report."""
        try:
            with self.lock:
                s = dict(self.st)
            self.watch.tick(now, s, self._diag_counters(s), self._diag_detail)
            if now >= self.next_status_line:
                self.next_status_line = now + 1.0
                self.status_lines.append(self.diag_line(s))
        except Exception:  # noqa: BLE001 - diagnostics must never take the supervisor down
            self.log.exception("diagnostics tick")

    def _diag_counters(self, s: dict) -> dict:
        # Lost and late are said apart (_rx_loop): "receive late +5" with
        # no overrun is the window costing latency, never samples.
        out = {"receive overruns": self.overruns, "receive late": self.rx_late}
        for where, st in (("device", s.get("deviceStatus") or {}), ("audio", s.get("audio") or {})):
            for k in self.DIAG_COUNTERS:
                v = st.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[f"{where} {k}"] = v
        return out

    def _diag_detail(self, key: str, s: dict) -> str:
        """More words for a logged change of `key` (the app adds its own)."""
        if key == "keyed":
            return f" ({s.get('txSource') or '-'}, tx dial {s.get('txDial', 0) / 1e6:.6f} MHz)"
        if key == "running" and s.get("running"):
            return f" (fs {s.get('fs', 0):g})"
        return ""

    def diag_line(self, s: dict) -> str:
        """One status line, as the status ring keeps it. `wait` (time a
        receive block spent waiting for the GIL/scheduler rather than
        running - _rx_loop) only appears once it is worth a second number:
        the 41% CPU this log showed on 07/10 while receive was actually
        starved is exactly the reading a hidden `wait` produces."""
        wait = 100 * float(s.get("cpuWait") or 0)
        wait_s = f" (wait {wait:.0f}%)" if wait > 10.0 else ""
        return (f"{time.strftime('%H:%M:%S')} {'RUN ' if s.get('running') else 'STOP'} "
                f"{str(s.get('mode', '')).upper():6s} {s.get('vfo', 0) / 1e6:.6f} MHz "
                f"{'TX ' if s.get('keyed') else ''}cpu {100 * float(s.get('cpu') or 0):4.1f}%{wait_s} "
                f"overruns {s.get('overruns', 0)} {self._diag_extra(s)}".rstrip()
                + (f" ! {s['error']}" if s.get("error") else ""))

    def _diag_extra(self, s: dict) -> str:
        """The app's part of a status line (NB: locks and corrections)."""
        return ""

    # ----------------------------------------------------------- memories, log
    def memories(self) -> list[dict]:
        return self.mem.listing()

    def save_memory(self, name: str, freq: float | None = None, mode: str | None = None) -> dict:
        m = self.mem.make(name, freq if freq is not None else self.st["vfo"], mode or self.st["mode"])
        with self.lock:
            self.mem.store(m)
            self.dirty = True
        return m

    def delete_memory(self, name: str) -> None:
        with self.lock:
            self.mem.remove(name)
            self.dirty = True

    def recall(self, name: str) -> dict:
        m = self.mem.find(name)
        return self.set(vfo=m[self.FREQ_KEY], mode=m["mode"])

    # ------------------------------------------------------- mode auto-tune
    def _mode_spots(self, mode: str) -> list[tuple[float, float, float]]:
        """Where `mode` is usually operated here, as (target, window_lo,
        window_hi) triples: inside a window the dial already counts as
        "there" (no retune wanted); otherwise set_mode_tuned moves to
        whichever target is nearest. Empty: the mode has no usual place
        (an app's own band plan/presets say so - ohsnb/bandplan.py
        MODE_SPOTS, ohsradio/radio.py's per-band lookup)."""
        return []

    def set_mode_tuned(self, mode: str) -> dict:
        """The operator picked a mode (a mode button or its shortcut - not
        a memory or band-stack recall, which already carries its own
        frequency): tunes to the mode's usual place too (Brian,
        07/10/2026), unless the dial is already there, Settings'
        modeAutoTune is off, or the radio is keyed - a retune must never
        move a transmission already on the air, so it is not even
        attempted (the mode still changes; RECHECK_KEYED unkeys it if the
        new mode cannot transmit where the dial already is, as for any
        other mode change while keyed).

        Playing a recording restricts where the dial may go
        (ohscore/devices/filedev.py); if the combined change is refused for
        that reason, the retune is dropped and only the mode changes - the
        operator asked for a mode, not a frequency, so the refusal is not
        shown."""
        target = None
        if self.st.get("modeAutoTune", True) and not self.st["keyed"]:
            target = mode_tune_target(self.st["vfo"], self._mode_spots(mode))
        if target is None:
            return self.set(mode=mode)
        try:
            changed = self.set(mode=mode, vfo=target)
        except ValueError:
            return self.set(mode=mode)
        self.toast(_("{mode}: tuned to {mhz:.3f}").format(mode=mode.upper(), mhz=target / 1e6))
        return changed

    def sstv_dir(self) -> Path:
        """Where received SSTV pictures are written (<data>/sstv)."""
        return self.data_dir / "sstv"

    def hsmodem_dir(self) -> Path:
        """Where files received from HSmodem stations are written (<data>/hsmodem)."""
        return self.data_dir / "hsmodem"

    def log_qso(self, call: str, **fields) -> dict:
        """Append a QSO to <data>/log.jsonl. Frequency and mode default to
        the radio's; time to now (UTC)."""
        return self.logbook.add(call, self.st["txDial"], self.st["mode"], **fields)

    def log_entries(self) -> list[dict]:
        return self.logbook.entries()

    def edit_qso(self, index: int, **fields) -> dict:
        """Change fields of the QSO at `index` in log_entries() order (the
        logbook view's row); see Logbook.edit."""
        return self.logbook.edit(index, **fields)

    def delete_qso(self, index: int) -> None:
        self.logbook.delete(index)

    def export_adif(self, path: Path | None = None) -> Path:
        """Write the whole log as ADIF 3 and return its path."""
        return self.logbook.export_adif(path, callsign=self.cfg.get("callsign", ""), locator=self.cfg.get("locator", ""))

    def _adif_fields(self, r: dict):
        """The app's ADIF fields for a log record (see ohscore.logbook)."""
        return [], []
