"""State registries: every key an engine has, as data.

The UI reads types, limits, choices and help text from a registry rather
than hard-coding them; the engine's `set()` validates against it; config
persists exactly the keys marked `persist`. Three kinds:

- **setting**: changed in the Settings dialog, persisted.
- **control**: an operating control on the main window (VFO, mode, volume...),
  persisted so the radio comes back where it was left - except that nothing
  here can make it come back *transmitting*.
- **status**: measured or derived by the engine; read-only to the UI.

`auth` marks keys that decide what or how hard we transmit beyond the
operator's normal controls (the gain ceiling, the safety timers, which
device). The engine's `set()` refuses them unless called with
`authorise=True`, which the UI passes only from its Settings dialog - so a
stray knob, shortcut or bug in the main window can never raise a ceiling.

`restart` marks keys that only take effect when the device is reopened
(`stop()` + `start()`, which the UI does after a settings save).

Each app builds one `Registry`: `add_shared_keys` puts in the keys both
apps have, with the same names and meanings (docs/ham/DESIGN-HAM.md
section 2.3); the app then narrows or rewords them with `override`, adds
its own keys, and adds cross-key rules. Key order is the order the app's
UI and state snapshot see, so an app's own keys can be placed among the
shared ones with `after()`.
"""
from __future__ import annotations

import copy
import math
from contextlib import contextmanager
from typing import Callable

from . import licences, pskreporter

from .i18n.text import _

# override() takes the same spellings add() does.
_RENAMED = {"lo": "min", "hi": "max"}


class Registry:
    def __init__(self, modes: list[str], digital: set[str]):
        self.spec: dict[str, dict] = {}
        # Modes the engine knows, in display order; `digital` are those run
        # by a decoder/encoder from ohscore.modes rather than the engine's own
        # demodulator.
        self.modes = modes
        self.digital = digital
        self._rules: list[Callable[[dict], None]] = []
        self._anchor: str | None = None

    # ------------------------------------------------------------ building
    def add(self, name, type_, default, kind, *, lo=None, hi=None, choices=None, unit="", persist=None, auth=False,
            restart=False, help="", validate=None):
        entry = {
            "type": type_, "default": default, "kind": kind, "min": lo, "max": hi, "choices": choices,
            "unit": unit, "persist": (kind != "status") if persist is None else persist, "auth": auth,
            "restart": restart, "help": help,
        }
        # A dict- or list-valued key (HAM's band stacks and power chains, the
        # converter list) checks its contents with `validate(value) ->
        # value`, raising ValueError with a sentence; only keys that need
        # one carry the field, so a key without it reads exactly as before.
        if validate is not None:
            entry["validate"] = validate
        if self._anchor is None:
            self.spec[name] = entry
            return
        items = list(self.spec.items())
        at = [k for k, _ in items].index(self._anchor) + 1
        items.insert(at, (name, entry))
        self.spec.clear()
        self.spec.update(items)
        self._anchor = name

    @contextmanager
    def after(self, key: str):
        """Keys added inside the block follow `key`, in the order added."""
        if key not in self.spec:
            raise KeyError(key)
        self._anchor = key
        try:
            yield
        finally:
            self._anchor = None

    def override(self, name: str, **kw) -> None:
        """Change fields of a key already added (an app narrowing a shared
        key's range, giving its own default or help). Fields keep their
        place, so the key's spec reads exactly as if added that way."""
        spec = self.spec[name]
        for k, v in kw.items():
            field = _RENAMED.get(k, k)
            if field not in spec:
                raise KeyError(f"{name}: no field {k!r}")
            spec[field] = v

    def rule(self, fn: Callable[[dict], None]) -> Callable[[dict], None]:
        """A cross-key check on a whole state dict; raises ValueError with
        an operator-readable sentence. Rules run in the order added."""
        self._rules.append(fn)
        return fn

    # ------------------------------------------------------------ using
    def defaults(self, kinds=("setting", "control", "status")) -> dict:
        return {k: (copy.deepcopy(v["default"]) if isinstance(v["default"], (dict, list)) else v["default"])
                for k, v in self.spec.items() if v["kind"] in kinds}

    def persisted(self) -> list[str]:
        return [k for k, v in self.spec.items() if v["persist"]]

    def coerce(self, key: str, value):
        """Validate one value against the spec; return it in canonical type or
        raise ValueError with a sentence an operator can read."""
        spec = self.spec.get(key)
        if spec is None:
            raise ValueError(_("There is no setting called {key}").format(key=repr(key)))
        t = spec["type"]
        label = key
        try:
            if t == "bool":
                if isinstance(value, str):
                    if value.lower() in ("1", "true", "on", "yes"):
                        value = True
                    elif value.lower() in ("0", "false", "off", "no"):
                        value = False
                    else:
                        raise ValueError
                value = bool(value)
            elif t == "int":
                if isinstance(value, bool) or float(value) != int(float(value)):
                    raise ValueError
                value = int(float(value))
            elif t == "float":
                if value is None and spec["default"] is None:
                    return None
                if isinstance(value, bool):
                    raise ValueError
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError
            elif t == "str":
                if not isinstance(value, str):
                    raise ValueError
                if "\n" in value or len(value) > 200:
                    raise ValueError
            elif t == "enum":
                if value not in spec["choices"]:
                    # Accept numeric enums sent as strings (sample rate from a text field).
                    matches = [c for c in spec["choices"] if str(c) == str(value)]
                    if not matches:
                        raise ValueError(_("{label} must be one of {choices}").format(
                            label=label, choices=", ".join(map(str, spec["choices"]))))
                    value = matches[0]
            elif t == "dict":
                if not isinstance(value, dict):
                    raise ValueError
                if spec.get("validate") is not None:
                    value = spec["validate"](value)
            elif t == "list":
                # Ordered values (the converter list, whose order is the
                # operator's, as in SDR Console's window).
                if not isinstance(value, list):
                    raise ValueError
                if spec.get("validate") is not None:
                    value = spec["validate"](value)
        except ValueError as e:
            if str(e):
                raise
            raise ValueError(_("{label} must be a {type}, not {value}").format(label=label, type=t, value=repr(value))) from None
        if t in ("int", "float") and value is not None:
            lo, hi = spec["min"], spec["max"]
            # With a unit and without are two whole sentences, not one with
            # an optional tail: a translation may put the unit elsewhere.
            unit = spec["unit"]
            if lo is not None and value < lo:
                msg = _("{label} cannot be below {lo:g} {unit}") if unit else _("{label} cannot be below {lo:g}")
                raise ValueError(msg.format(label=label, lo=lo, unit=unit))
            if hi is not None and value > hi:
                msg = _("{label} cannot be above {hi:g} {unit}") if unit else _("{label} cannot be above {hi:g}")
                raise ValueError(msg.format(label=label, hi=hi, unit=unit))
        return value

    def check_combined(self, st: dict) -> None:
        """Rules that span several keys. Raises ValueError."""
        for fn in self._rules:
            fn(st)



def _clean_sessions(value: list) -> list:
    """decoderSessions: a list of {decoder, freqHz, params}, at most 16."""
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError(_("decoderSessions must be a list of at most 16 sessions"))
    out = []
    for v in value:
        if not isinstance(v, dict) or not isinstance(v.get("decoder"), str) or not v["decoder"]:
            raise ValueError(_("Each decoder session needs a decoder"))
        try:
            freq = float(v.get("freqHz"))
        except (TypeError, ValueError):
            raise ValueError(_("Each decoder session needs a frequency in hertz")) from None
        params = v.get("params") or {}
        if not isinstance(params, dict) or not all(isinstance(x, (bool, int, float, str)) for x in params.values()):
            raise ValueError(_("A decoder session's settings must be plain values"))
        out.append({"decoder": v["decoder"][:32], "freqHz": freq, "params": dict(params)})
    return out

def add_shared_keys(reg: Registry) -> None:
    """The keys both apps have. Help text here is the app-neutral wording;
    an app that means something narrower (a QO-100 downlink dial, say)
    says so with `override`."""
    k = reg.add

    # --- device -----------------------------------------------------------------
    k("device", "enum", "sim", "setting", choices=["sim", "pluto", "soapy"], auth=True, restart=True,
      help="Which radio. The simulator needs no hardware and is the default.")
    k("plutoUri", "str", "ip:192.168.2.1", "setting", auth=True, restart=True,
      help="libiio URI: ip:192.168.2.1 (Pluto over USB), ip:pluto.local, ip:<address> (Pluto+, LibreSDR), usb:<bus>.<dev>.<n>.")
    k("soapyArgs", "str", "driver=rtlsdr", "setting", restart=True,
      help="SoapySDR device arguments for a receive-only SDR, e.g. driver=airspy.")
    k("soapyAntenna", "str", "", "setting",
      help="The receiver's antenna input, as its driver names it (an SDRplay RSPdx: Antenna A, Antenna B or "
           "Antenna C). Empty: the driver's default. Applied live, with no restart, where the driver allows it.")
    k("soapyAntennaLabels", "str", "", "setting",
      help="A name for each antenna input (\"Antenna C\" -> \"80 m dipole\"), as one line of JSON "
           "({\"Antenna C\": \"80 m dipole\"}): Settings' Radio page writes and reads it with a table, never by "
           "hand.")
    k("sampleRate", "enum", 1_200_000, "setting", choices=[1_200_000], unit="S/s", restart=True,
      help="Complex sample rate shared by receive and transmit.")
    k("rxGainMode", "enum", "slow_attack", "setting", choices=["manual", "slow_attack", "fast_attack"],
      help="Receiver gain control in the SDR.")
    k("rxGain", "float", 40.0, "setting", lo=0.0, hi=73.0, unit="dB", help="Receiver gain when gain control is manual.")

    # --- operating controls -------------------------------------------------------
    k("vfo", "float", 0.0, "control", unit="Hz", help="Receive dial.")
    k("mode", "enum", "usb", "control", choices=reg.modes)
    k("split", "bool", False, "control", help="Transmit on txVfo instead of following the receive dial.")
    k("txVfo", "float", 0.0, "control", unit="Hz", help="Transmit dial when split is on.")
    k("rit", "float", 0.0, "control", lo=-5000.0, hi=5000.0, unit="Hz")
    k("ritOn", "bool", False, "control")
    k("xit", "float", 0.0, "control", lo=-5000.0, hi=5000.0, unit="Hz")
    k("xitOn", "bool", False, "control")
    k("filterLo", "float", 300.0, "control", lo=0.0, hi=1000.0, unit="Hz", help="SSB/digital receive filter low edge.")
    k("filterHi", "float", 2700.0, "control", lo=1000.0, hi=4000.0, unit="Hz", help="SSB/digital receive filter high edge.")
    k("cwWidth", "float", 500.0, "control", lo=50.0, hi=1500.0, unit="Hz")
    k("cwPitch", "float", 700.0, "control", lo=300.0, hi=1200.0, unit="Hz")
    k("freedvMode", "enum", "700d", "control", choices=["700d", "700c", "700e", "1600", "2020"],
      help="FreeDV waveform. Only those the installed libcodec2 can open are usable (caps lists them).")
    k("amWidth", "float", 3000.0, "control", lo=1000.0, hi=5000.0, unit="Hz", help="AM filter, either side of carrier.")
    k("agc", "enum", "medium", "control", choices=["off", "fast", "medium", "slow"])
    k("rfGain", "float", 0.0, "control", lo=-20.0, hi=60.0, unit="dB", help="Fixed audio gain when AGC is off.")
    k("nb", "bool", False, "control", help="Impulse noise blanker.")
    k("nbThreshold", "float", 8.0, "control", lo=3.0, hi=30.0, help="Blank samples this many times the mean level.")
    k("nr", "bool", False, "control",
      help="Noise reduction (WDSP's NR2) on what you hear in the voice modes and CW. Decoders always get the "
           "audio without it.")
    k("nrStrength", "float", 50.0, "control", lo=0.0, hi=100.0, unit="%",
      help="How far noise reduction may pull the noise down: 0 % leaves the audio untouched, 100 % up to 40 dB.")
    k("volume", "float", 0.5, "control", lo=0.0, hi=1.0)
    k("mute", "bool", False, "control")
    k("micGain", "float", 0.0, "control", lo=-20.0, hi=30.0, unit="dB")
    k("compressor", "float", 6.0, "control", lo=0.0, hi=20.0, unit="dB", help="Speech compression (0 = off).")
    k("txFilterLo", "float", 300.0, "setting", lo=50.0, hi=1000.0, unit="Hz")
    k("txFilterHi", "float", 2700.0, "setting", lo=1500.0, hi=2950.0, unit="Hz", help="Transmit audio high edge.")
    k("monitor", "bool", False, "control", help="Hear your own transmit audio.")
    k("monitorLevel", "float", 0.3, "control", lo=0.0, hi=1.0)
    k("cwWpm", "float", 20.0, "control", lo=5.0, hi=50.0, unit="wpm")
    k("pttMode", "enum", "hold", "control", choices=["hold", "toggle"], help="How the UI's space bar keys (UI-side).")
    k("modeAutoTune", "bool", True, "control",
      help="Picking a mode with a usual operating frequency (FT8, FT4, CW ...) tunes there, unless the dial is "
           "already in its usual place or the radio is keyed (UI-side: Engine.set_mode_tuned).")
    # The voice keyer (ohscore/keyer.py, Engine.send_voice). Repeat is for
    # this run only, as playLoop is: a program that starts calling CQ on
    # its own because it did last week would be a surprise. The interval
    # is a preference and is kept; at least a second, so the operator
    # always has a gap to answer in (and the next over never starts on the
    # thread still ending the last).
    k("keyerRepeat", "bool", False, "control", persist=False,
      help="Send a voice memory again and again, keyerRepeatSec after each ends, until PTT, Esc or a retune.")
    k("keyerRepeatSec", "float", 10.0, "control", lo=1.0, hi=300.0, unit="s",
      help="Voice keyer: the pause between repeats, listening for a reply.")

    # --- safety -------------------------------------------------------------------
    k("txTimeoutSec", "float", 300.0, "setting", lo=10.0, hi=1800.0, unit="s", auth=True,
      help="Unkey after this long transmitting.")
    k("deadAirSec", "float", 3.0, "setting", lo=1.0, hi=30.0, unit="s", auth=True,
      help="Voice modes: unkey after this long with no microphone audio.")
    k("watchdogSec", "float", 2.0, "setting", lo=0.5, hi=10.0, unit="s", auth=True,
      help="Unkey if the user interface stops servicing the engine for this long.")

    # --- scopes -------------------------------------------------------------------
    k("wideBins", "int", 2048, "control", lo=256, hi=8192, help="Bins across the wide scope.")
    k("wideAvg", "int", 2, "control", lo=1, hi=16, help="FFTs averaged per wide line.")
    k("zoomSpanHz", "float", 12_000.0, "control", lo=2_000.0, hi=50_000.0, unit="Hz")
    k("zoomBins", "int", 1024, "control", lo=128, hi=4096)
    k("zoomAvg", "int", 2, "control", lo=1, hi=16)
    k("zoomPan", "float", 0.0, "control", lo=-25_000.0, hi=25_000.0, unit="Hz",
      help="Zoom scope centre relative to the receive dial.")
    k("scopeFps", "float", 20.0, "control", lo=1.0, hi=50.0, unit="lines/s")

    # --- audio --------------------------------------------------------------------
    k("audioBackend", "enum", "portaudio", "setting", choices=["portaudio", "null"], restart=True,
      help="null runs with no sound card (headless, tests).")
    k("audioIn", "str", "", "setting", restart=True, help="Microphone device name; empty for the system default.")
    k("audioOut", "str", "", "setting", restart=True, help="Speaker device name; empty for the system default.")
    k("audioOut2", "str", "", "setting", restart=True,
      help="Optional second output carrying receive audio to other software (e.g. a loopback device).")

    # --- station ------------------------------------------------------------------
    k("callsign", "str", "", "setting")
    k("locator", "str", "", "setting")
    # Where the station is and whose licence it transmits under
    # (ohscore/countries.py, ohscore/licences; Brian, 08/10/2026: both apps
    # for use abroad). The country follows the callsign - its prefix, for
    # EA8/GM4BRI - until the operator picks one; the licence follows the
    # country until the operator picks one. Licence keys are `auth`: they
    # decide where the transmitter may go.
    k("stationCountry", "str", "", "setting",
      help="The station's country (a DXCC entity's prefix, e.g. GM, EA8, K). Empty: worked out from your callsign - "
           "the prefix's country when you sign EA8/GM4BRI.")
    k("licence", "enum", licences.AUTO, "setting", choices=[licences.AUTO, licences.CUSTOM] + list(licences.REGIMES),
      auth=True,
      help="The licence whose conditions the transmit guard enforces. auto: the station country's, where one is "
           "written; custom: the segments and power limits you enter yourself.")
    # No default class (Brian, 05/10/2026): a default wrong for most people
    # is worse than a one-time choice. The choices are every written
    # regime's classes; the guard refuses one that is not the regime in
    # force's (one regime's "full" is not another's).
    k("licenceClass", "enum", "", "setting", choices=[""] + licences.all_class_ids(), auth=True,
      help="Your licence class, within the licence in force. There is no default: until you choose one, transmit "
           "is refused (receiving works).")
    k("stationConditions", "dict", {}, "setting", auth=True, validate=licences.clean_conditions,
      help="Your answers to the licence's questions about where the station is (near an excluded area, "
           "notified an authority...), by the licence's own keys. An unanswered one takes the licence's default, "
           "the restrictive side.")
    k("customLicence", "list", [], "setting", auth=True, validate=licences.clean_custom,
      help="Your own licence, for a country whose rules are not written into OpenHamShack: each segment's lower and "
           "upper edge (Hz), most power and its unit (PEP, mean, ERP, EIRP), and whether satellite uplinks are "
           "allowed there. Used when Licence is 'custom'.")
    # The FT8/FT4 sequencer's DX call, so the decoder - which lives with the
    # engine, not the panel - can tell jt9 who is being worked, as WSJT-X's
    # DX Call box tells its decoder. Not kept: a QSO does not outlive the run.
    k("dxCall", "str", "", "control", persist=False,
      help="The station being worked in FT8/FT4, for the decoder's a-priori passes; empty for none.")
    # Which FT8/FT4 decoder comes first (ohscore/modes/ft8.py). Automatic is
    # ohsdigi where it is built, jt9 where it is not - Brian's choice of
    # 07/10/2026, after ohsdigi matched jt9 on real slots; jt9 is for an
    # operator who wants WSJT-X's own decoder or wants to compare. Asked at
    # every slot, so it applies without a restart.
    k("ft8Decoder", "enum", "auto", "setting", choices=["auto", "jt9"],
      help="Automatic decodes with OpenHamShack's own decoder, a port of WSJT-X 2.7.0's, and falls back to WSJT-X's jt9 "
           "if it is missing or fails. WSJT-X's jt9 puts jt9 first. Whichever is not decoding checks the other's "
           "work, where both are installed.")

    # --- decoders (ohscore/decoders.py, shack_sdr; RADIO-SDR-PLAN §3.4, §4.3) ---------
    # Fixed-frequency decoder sessions, beside the mode decoder: how many may
    # run, the processor time they may share (the host pauses the newest
    # when they would take more, never the mode decoder), and the sessions
    # themselves, which start again with the radio. Both limits take effect
    # when the radio next starts: the host is made with them.
    k("decodersMax", "int", 4, "setting", lo=0, hi=16, restart=True,
      help="How many decoders may run on frequencies of their own, beside the mode's decoder.")
    k("decodeCpuMax", "float", 0.25, "setting", lo=0.05, hi=1.0, restart=True,
      help="The share of one processor core the decoders may use between them. Past it the newest is paused until "
           "there is room; the mode's own decoder is never paused.")
    k("decoderSessions", "list", [], "setting", validate=_clean_sessions,
      help="The decoders running on frequencies of their own, started again with the radio: each one's decoder, "
           "frequency (Hz) and settings.")

    # --- IQ recording (ohscore/sigmf.py) --------------------------------------------
    k("recLimitMin", "float", 0.0, "setting", lo=0.0, hi=600.0, unit="min",
      help="Stop an IQ recording by itself after this many minutes (0: only when you stop it). At 1.2 MS/s a "
           "minute takes about 290 MB.")
    # Playback (ohscore/devices/filedev.py): an operator's choice for this
    # run, so not kept - a program that starts looping a file because it
    # did last week would be a surprise.
    k("playLoop", "bool", False, "control", persist=False,
      help="Start an IQ recording again from the beginning when it ends.")

    # --- updates (ohscore/update.py; the window does the checking) ----------------
    # A setting of the engine's although only the window reads it, so that
    # it is kept in config.json with the operator's other choices and shows
    # in Settings like them. On by default: Brian's decision (07/10/2026).
    k("checkUpdates", "bool", True, "setting",
      help="Look for a new version when the program starts and once a day while it runs. The check fetches one "
           "small signed file from the program's website and sends nothing about you or this computer. Off: "
           "only Help › Check for updates… looks.")

    # --- spotting (ohscore/pskreporter.py) ------------------------------------------
    # Off by default and refused without a callsign and locator (the rule
    # below): Brian's decision that nothing leaves the machine until the
    # operator asks (docs/ham/DESIGN-HAM.md section 12). Applies at once.
    k("pskReporter", "bool", False, "setting",
      help="Send the callsigns you decode in FT8, FT4, Q65 and JS8 to PSKReporter every five minutes: their "
           "call, frequency, mode, signal report and grid, with your callsign, locator and this program's name.")

    # --- simulator (device "sim") ------------------------------------------------
    k("simSignals", "bool", True, "setting", restart=True, help="Populate the simulated band with other stations.")
    k("simSeed", "int", 0, "setting", lo=0, hi=2**31 - 1, restart=True, help="0 = different every run.")
    k("simRealtime", "bool", True, "setting", persist=False, restart=True,
      help="Pace the simulator to real time (tests turn this off to run faster).")

    # --- status (read-only) -------------------------------------------------------
    for name, type_, default, help_ in [
        ("running", "bool", False, "The engine has the device open and is receiving."),
        ("keyed", "bool", False, "Transmitting."),
        ("txSource", "str", "", "What is keying: ptt, send:<mode>, tune, voice:<n> (voice memory n)."),
        ("txSeconds", "float", 0.0, "Seconds into the current transmission."),
        ("txOnAir", "bool", False, "The over is on the air: past its slot wait and key-up. keyed is true from "
                                   "the moment an over is queued, so a timed FT8 over is keyed for most of the "
                                   "slot before it; this is what an on-air light should follow."),
        ("txStartAt", "float", 0.0, "When the queued over's audio is due (UTC seconds), for a timed one (FT8, "
                                    "FT4, Q65, JS8); 0 otherwise."),
        ("canTx", "bool", False, "The open device can transmit."),
        ("simWhy", "str", "", "Why the open device is the simulator, as a sentence for the operator ('' when it "
                              "is not, or nothing is open)."),
        ("simFallback", "bool", False, "The simulator is standing in for a radio that was asked for and could "
                                       "not be had (simWhy says why)."),
        ("txBlocked", "str", "", "Why keying here would be refused right now ('' = it would not)."),
        ("station", "dict", {}, "Where the station is and the licence in force (ohscore/countries.py InForce.info): "
                                "entity, region, country, regime, its classes, why transmit is locked when no "
                                "licence is in force, and notes (abroad, CEPT, QO-100's footprint)."),
        ("txWarning", "dict", {}, "The transmit card's one standing warning: {key, level, text} of the most "
                                  "important transmit condition now ({} = none). Engine.tx_warn / tx_clear."),
        ("rxDial", "float", 0.0, "Frequency the receiver is demodulating (vfo + RIT)."),
        # The demodulator's real edges, so a client draws the passband the
        # radio hears rather than its own guess per mode: wide FM's 180 kHz
        # is a figure no client could know (RADIO-LISTEN-CONTRACT §1).
        ("rxFilterLo", "float", 0.0, "The receive passband's lower edge, Hz from the receive dial, as the "
                                     "demodulator uses it in the current mode (negative below the dial)."),
        ("rxFilterHi", "float", 0.0, "The receive passband's upper edge, Hz from the receive dial."),
        ("txDial", "float", 0.0, "Frequency our transmission is meant to land on (txVfo or vfo, + XIT)."),
        ("segment", "str", "", "Bandplan segment under the receive dial."),
        ("fs", "float", 0.0, "Device sample rate."),
        ("cpu", "float", 0.0, "Receive thread's own CPU time (time.thread_time()) as a fraction of real time."),
        ("cpuWait", "float", 0.0, "Extra wall-clock time a receive block took beyond its own CPU time - waiting "
                                  "for the GIL or the OS scheduler, not doing work. High while cpu stays low means "
                                  "receive is starved rather than busy."),
        ("overruns", "int", 0, "Times receive lost samples: the radio's stream had a gap (a stalled link, a "
                               "busy USB bus) or processing fell more than two seconds behind. On a device "
                               "read without the prefetch queue (ohscore/rxprefetch.py), blocks processed "
                               "slower than real time, the best sign of loss there is."),
        ("rxLate", "int", 0, "Receive blocks that took longer to process than they last. Behind the prefetch "
                             "queue these cost latency, not samples."),
        ("rxLostS", "float", 0.0, "Seconds of receive samples lost in all (see overruns)."),
        ("rxBehindS", "float", 0.0, "Seconds of receive read from the radio and not yet processed."),
        ("rxStreamPct", "float", 100.0, "Share of the radio's stream that reached the program over the last ten "
                                        "seconds, percent (100: nothing known to be missing)."),
        ("deviceStatus", "dict", {}, "Device status, shown verbatim."),
        ("audio", "dict", {}, "Audio status: devices, rates, buffer fill."),
        ("modes", "dict", {}, "Per mode: whether it can decode/encode here, or the sentence saying what to install."),
        ("error", "str", "", "Why the engine is not running, if it is not."),
        ("recording", "bool", False, "Receive IQ is being recorded."),
        ("recFile", "str", "", "The recording's .sigmf-data file (the last one, once it has stopped)."),
        ("recSeconds", "float", 0.0, "Seconds of IQ in the recording."),
        ("recBytes", "int", 0, "Bytes of IQ written to the recording so far."),
        ("recDropped", "int", 0, "Samples the recording lost because the disk could not keep up."),
        ("recRxLost", "int", 0, "Samples the recording is missing because the receive stream never delivered "
                                "them (a stalled link to the radio), counted apart from the disk's."),
        ("playing", "bool", False, "An IQ recording is being played instead of the radio (start_playback)."),
        ("playFile", "str", "", "The .sigmf-data file being played."),
        ("playPos", "float", 0.0, "Seconds into the recording."),
        ("playLength", "float", 0.0, "The recording's length, seconds."),
        ("playUtc", "float", 0.0, "When the sample being played was recorded (UTC, seconds since 1970)."),
        ("playEnded", "bool", False, "The recording has been played to its end (and is not looping)."),
        ("autoBusy", "str", "", "What is listening to the receive channel now: tune (auto-tune), audio (best "
                                "audio), or '' for nothing."),
        ("autoHeard", "int", 0, "Seconds of the station auto-tune or best audio has heard so far (while "
                                "autoBusy)."),
        ("autoTune", "str", "", "What the last auto-tune did: how far it moved the dial (or RIT) and what it "
                                "measured."),
        ("autoTuneRefused", "str", "", "Why the last auto-tune refused to move anything ('' when it did)."),
        ("autoAudio", "str", "", "What best audio last measured and chose, in one line."),
        ("autoAudioWhy", "str", "", "Best audio's reason for each choice, one line per setting."),
        ("autoAudioRefused", "str", "", "Why the last best audio changed nothing ('' when it applied)."),
        ("ft8DecoderInUse", "str", "", "The decoder FT8/FT4 decodes are coming from: ohsdigi, jt9, or 'jt9 (ohsdigi "
                                       "failed)' after a fallback; '' in other modes."),
        ("decoderMissing", "str", "", "Why the chosen mode cannot be decoded here (no decoder in this installation, "
                                      "or it failed to start); '' when it can, or the mode needs none."),
        ("decoders", "dict", {}, "The decoder sessions (ohscore/decoders.py): available, how many run, the "
                                 "processor share they may use, and which codecs are missing (null until the "
                                 "first look)."),
    ]:
        k(name, type_, default, "status", help=help_)

    @reg.rule
    def _spotting_needs_station(st):
        if not st.get("pskReporter"):
            return
        if not pskreporter.valid_call(st.get("callsign", "")) or not pskreporter.valid_locator(st.get("locator", "")):
            raise ValueError(_("PSKReporter needs your callsign and locator (e.g. IO86 or IO86ha) on the Station page "
                               "before it can be turned on - every spot says who heard it and where."))

    @reg.rule
    def _rx_filter_width(st):
        if st["filterHi"] - st["filterLo"] < 100:
            raise ValueError(_("The receive filter must be at least 100 Hz wide"))
