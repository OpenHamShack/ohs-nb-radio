"""The IC-9700 diagnostic: Settings > Transmitter's "IC-9700 diagnostic…",
and `python3 -m ohsnb --rig-diagnostic`.

Asked for on 12/10/2026, after Ray's first level set failed on the first
real IC-9700 NB met (23 cm into a dummy load, Windows): what Brian got
back was a sentence from the assistant, and every question after it -
which port, what the menus said, how fast the radio answers, what the
meters do with a tone - needed Ray at the radio and Brian on the phone.
This gathers all of it in one plain-text report that the operator copies
or saves and sends. Two parts:

1. **Read-only** (`read_only`), always first, never transmits: the
   computer's serial ports, which one answers and at what CI-V address,
   the transceiver ID, MAIN (and SUB when it is the selected band),
   satellite mode, DATA MOD and DATA OFF MOD, USB MOD Level, RF POWER,
   whether it is transmitting, the meters on receive; the time of 20
   frequency reads and any echo, other traffic or collision seen; the
   sound devices and which is chosen; NB's own rig settings and the
   upconverter. Every one of those is a read the CI-V whitelist already
   allows (ohscore/rig/civ.py), on the setup assistant's turn on the port
   (RigSetup._port: NB's link paused, CAT overs refused).
2. **Keyed** (`keyed`), only with the dummy-load tick *and* a confirmation
   naming the band and the RF POWER about to be used: four short overs,
   each a ToneOver (ohsnb/rigsetup.py) - the level set's kind of over, the
   one tone Radio._cat_req lets through besides a send(), so the same
   guard, permit, sound device, delay, tail, time-out, watchdog, Halt and
   Escape as an FT8 over, and nothing new that can key the radio:
   keyed with no audio; a tone at -40, -34, -28 and -22 dB; at -16, -10
   and the operator's own level; and one at the operator's level that
   ends by itself, sampled fast, for the key-up -> Po and audio end ->
   PTT off times (the PTT delay and tail). Po and ALC are read three
   times at each step, after the step's audio has reached the radio
   (ToneOver.set_level). At most MAX_S each, a second apart.

Decisions:

- **It says what Ray's first report needed a person to work out**
  (12/10/2026: his 9700 answered only at 19200 baud, and NB played its
  tone into his other radio's USB Audio CODEC - keyed, Po 0 at every
  level). The reads try every baud rate (civ.find_radio); with more than
  one CODEC the report lists them and the one on the radio's USB hub
  (ohscore/rig/usbpair.py), and says when NB's choice is not it; and
  keyed overs that make no power at any level end in a VERDICT line
  naming the sound device, rather than a table to puzzle over.
- **It changes nothing on the radio.** Not even what the sweep might
  want: RF POWER is read, never written (no permit can name that write),
  and the overs run on the band and at the power the radio already has -
  the confirmation names both, so "never more power than it is set to"
  is true by construction. The radio's settings are read before and
  after the overs and the report says whether anything differs. The one
  thing an over does to the radio, USB-D, is what NB's CAT PTT path
  already holds whenever a digital mode is chosen, which the keyed part
  requires.
- **Nothing that identifies the station or the radio's owner.** No
  callsign, locator, name or serial number: NB's settings are a fixed
  list of the rig's, and serial numbers are taken out of port names and
  descriptions (Linux names the 9700's port after its serial).
- **The report is English, not translated:** it is read by the people
  who wrote NB, not by the operator, and a translated report would be
  read back through a dictionary. Its sentences are therefore plain
  strings, not _() - the window's own words around it are translated.
- **The command line keys only with an explicit promise.** Over SSH no
  operator is there to tick a box, so `--keyed` refuses unless
  `--i-have-a-dummy-load-and-operator-present` is given as well; with it,
  the same two confirmations are taken as given.
"""
from __future__ import annotations

import logging
import platform
import re
import statistics
import threading
import time
from pathlib import Path

from ohscore import diag
from ohscore.rig import RigError, RigTimeout, civ, usbpair

from ohsnb.i18n import _

from .extrig import IF_BAND_NAMES, plan_from
from .rigsetup import MAX_S, PO_NONE, READ_GAP_S, RigSetup, ToneOver, _band_of, _pct, find_codec

log = logging.getLogger("ohsnb.rigdiag")

SWEEPS = ((-40.0, -34.0, -28.0, -22.0), (-16.0, -10.0, "op"))
SAMPLES = 3                    # meter readings per step
GAP_S = 1.0                    # between overs
TIMING_S = 2.0                 # the timing over's tone: it ends by itself
TIMING_POLL_S = 0.005
TIMING_AFTER_S = 0.8           # Po read on after PTT off
TIMED_READS = 20
RADIO_READY_MS = 65            # Ray's 9700 (12/10/2026): key-up to half power, the audio already playing
DELAY_MIN_MS = 80              # the PTT delay recommended at least: that, and a margin
# The IC-9700's output range per band (specification: 144 and 430 MHz
# 0.5-100 W and 0.5-75 W, 1200 MHz 0.1-10 W): RF POWER 0-100 % between
# them, as near as the confirmation needs.
WATTS = {"2m": (0.5, 100.0), "70cm": (0.5, 75.0), "23cm": (0.1, 10.0)}
LOOKS_LIKE_9700 = ("9700", "cp210", "silicon labs")
NB_SETTINGS = ("txRadio", "civPort", "civBaud", "civAddress", "rigIfBand", "rigCatPtt", "rigTxAudioOut",
               "rigTxAudioDb", "rigPttDelayMs", "rigPttTailMs", "rigPollMs", "mode")


def scrub(text) -> str:
    """Serial numbers out of a port name or description: Linux's by-id
    names (…IC-9700_13003524_A-if00-port0) and pyserial's SER=: also any
    run of six digits or more, which no port name needs. Every error the
    driver or pyserial raised goes through here too, not only the names:
    pyserial's "could not open port …" quotes the by-id path whole, and
    until 0.1.18 a 9700 that was unplugged put its serial number in the
    report that way. The family's shared rules (diag.scrub_serials, which
    every upload also runs) go first; the six-digit rule stays here only,
    where the text is a port name or an error and not a log full of
    frequencies."""
    return re.sub(r"\d{6,}", diag.SERIAL, diag.scrub_serials(text))


def watts(band: str, rf: int | None) -> float | None:
    lo_hi = WATTS.get(band)
    if lo_hi is None or rf is None:
        return None
    lo, hi = lo_hi
    return lo + (hi - lo) * rf / 255


def list_ports() -> list[tuple[str, str]]:
    """(device, description) of every serial port pyserial sees; empty
    without pyserial."""
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return []
    out = []
    for p in sorted(lp.comports(), key=lambda p: p.device):
        out.append((p.device, " ".join(x for x in (p.description, p.hwid) if x and x != "n/a")))
    return out


class RigDiagnostic:
    def __init__(self, radio, changes: dict | None = None):
        self.radio = radio
        self.setup = RigSetup(radio, changes)
        self.cfg = self.setup.cfg
        self.cancelled = threading.Event()
        self.parts: dict[str, dict] = {}

    def _finished(self, what: str, part: dict, detail: str) -> None:
        """A part is done: its report joins the next diagnostics bundle and,
        for an operator who has opted in, sends one (ohscore/diagupload.py)."""
        self.parts[what] = part
        diag.attach("ic9700-diagnostic.txt", RigDiagnostic.report(self.parts.get("reads"), self.parts.get("keyed")))
        if part.get("facts", {}).get("noAudio"):
            diag.notable("no-power-out", "the IC-9700 diagnostic: keyed, no power at any level")
        diag.notable("ic9700-diagnostic", detail)

    def cancel(self) -> None:
        """Stop: the over on the air ends at once (Halt), and no further
        over starts."""
        self.cancelled.set()
        self.radio.halt()

    # ------------------------------------------------------------ 1. reads
    def read_only(self, ports=list_ports) -> dict:
        """The read-only part: {"sections": [(title, [lines])], "facts"}.
        Never raises for a radio that does not answer: that is a finding."""
        facts: dict = {}
        sections = [("This computer", self._computer())]
        found = ports()
        lines = [f"{scrub(dev)}: {scrub(desc) or '(no description)'}" for dev, desc in found] or \
            ["none listed (or pyserial missing)"]
        sections.append(("Serial ports", lines))
        sections.append(("The IC-9700 by CI-V", self._radio_reads(found, facts)))
        sections.append(("Sound devices", self._sound(facts)))
        sections.append(("NB's rig settings", self._nb_settings()))
        log.info("IC-9700 diagnostic: read-only part done (%s)", "answered" if facts.get("answered") else
                 "no answer")
        out = {"sections": sections, "facts": facts}
        self._finished("reads", out, "read-only checks done")
        return out

    def _computer(self) -> list[str]:
        return [f"OpenHamShack QO-100 NB {diag.app_version('ohsnb') or '?'}", f"OS: {diag._os_name()}",
                f"Python {platform.python_version()}", time.strftime("Run at %Y-%m-%d %H:%M:%S UTC", time.gmtime())]

    def _try(self, lines: list, label: str, fn, fmt=str):
        try:
            v = fn()
        except RigTimeout:
            lines.append(f"{label}: no answer")
            return None
        except RigError as e:
            lines.append(f"{label}: refused ({scrub(e)})")
            return None
        lines.append(f"{label}: {fmt(v)}")
        return v

    def _radio_reads(self, found, facts: dict) -> list[str]:
        cfg = self.cfg
        port = cfg.get("civPort") or ""
        baud = int(cfg.get("civBaud", 115200))
        addr = int(cfg.get("civAddress", civ.IC9700))
        lines = [f"NB's port {scrub(port) or '(none set)'} at {baud} baud, CI-V address {addr:02X}h"]
        try:
            with self.setup._port():
                candidates = [port] if port else []
                candidates += [d for d, desc in found if d != port
                               and any(k in f"{d} {desc}".lower() for k in LOOKS_LIKE_9700)]
                answered = None
                for p in candidates:
                    got = self._probe(p, baud, addr, lines)
                    if got is not None and answered is None:
                        answered = (p, got[0])
                if answered is None and port:
                    lines.append(f"Looking for the radio on {scrub(port)} at every baud rate, then every CI-V "
                                 f"address (up to about twenty seconds)")
                    try:
                        hit = civ.find_radio(port, baud, addr)
                    except RigError as e:
                        hit = None
                        lines.append(f"  {scrub(e)}")
                    if hit:
                        answered = (port, hit[0])
                        baud = hit[2]
                        lines.append(f"  it answers at {hit[0]:02X}h and {hit[2]} baud: set CI-V address "
                                     f"{hit[0]:02X} and baud {hit[2]} in Settings > Transmitter (Find does)")
                    else:
                        lines.append("  nothing answered at any rate or address")
                if answered is None:
                    lines.append("No IC-9700 answered: nothing more could be read from it")
                    return lines
                facts["answered"] = {"port": answered[0], "address": answered[1], "baud": baud}
                rig = civ.CivRig(answered[0], baud, answered[1])
                rig.open()
                try:
                    self._reads(rig, lines, facts)
                finally:
                    rig.close()
        except RigError as e:
            lines.append(f"Could not use the port: {scrub(e)}")
        return lines

    def _probe(self, port: str, baud: int, addr: int, lines: list) -> tuple[int, int] | None:
        rig = civ.CivRig(port, baud, addr)
        try:
            rig.open()
        except RigError as e:
            lines.append(f"{scrub(port)}: would not open ({scrub(e)})")
            return None
        try:
            t = time.monotonic()
            ident = rig.read_id()
            lines.append(f"{scrub(port)}: answers at {addr:02X}h in {1000 * (time.monotonic() - t):.0f} ms, "
                         f"transceiver ID {ident:02X}h")
            return addr, ident
        except RigTimeout:
            lines.append(f"{scrub(port)}: no answer at {addr:02X}h")
        except RigError as e:
            lines.append(f"{scrub(port)}: answered with a refusal at {addr:02X}h ({scrub(e)})")
            return addr, addr
        finally:
            rig.close()
        return None

    def _reads(self, rig, lines: list, facts: dict) -> None:
        lines.append("Firmware version: not readable over CI-V")
        sel = self._try(lines, "Selected band (07 D2)", rig.read_selected, lambda v: v.upper())
        sat = self._try(lines, "Satellite mode (16 5A)", rig.read_satellite, lambda v: "on" if v else "off")
        hz = self._try(lines, f"{(sel or 'selected').upper()} frequency (03)", rig.read_freq, _mhz)
        self._try(lines, f"{(sel or 'selected').upper()} mode (04, 1A 06)", rig.read_mode,
                  lambda v: f"{v[0].upper()}{'-D' if v[1] else ''}")
        main = hz if sel == "main" else None
        if sel != "main":
            main = self._try(lines, "MAIN frequency (25 00)", rig.read_main_freq, _mhz)
        if sel == "main":
            lines.append("SUB: not read (it would need SUB selected, a change NB does not make here)")
        facts["mainHz"] = main
        facts["satellite"] = sat
        mi = self._try(lines, "MOD Input (1A 05 01 15 / 16)", rig.read_mod_input,
                       lambda v: f"DATA OFF MOD {(v.get('plain') or '?').upper()}, "
                                 f"DATA MOD {(v.get('data') or '?').upper()}")
        facts["dataMod"] = (mi or {}).get("data")
        usb = self._try(lines, "USB MOD Level (1A 05 01 13)", rig.read_usb_mod_level, lambda v: f"{v} ({_pct(v)} %)")
        rf = self._try(lines, "RF POWER (14 0A)", rig.read_rf_power, lambda v: f"{v} ({_pct(v)} %)")
        facts["usbMod"], facts["rfPower"] = usb, rf
        band = _band_of(main)
        w = watts(band, rf)
        if w is not None:
            lines.append(f"  about {w:.1f} W on {IF_BAND_NAMES.get(band, band)} (from the 9700's range for the band)")
        self._try(lines, "Transmitting (1C 00)", rig.read_tx, lambda v: "yes" if v else "no")
        self._try(lines, "Meters on receive (15 11 Po, 15 13 ALC)",
                  lambda: (rig.read_meter("po"), rig.read_meter("alc")), lambda v: f"Po {v[0]}, ALC {v[1]}")
        times, fails = [], 0
        for _i in range(TIMED_READS):
            t = time.monotonic()
            try:
                rig.read_freq()
                times.append(1000 * (time.monotonic() - t))
            except RigError:
                fails += 1
        if times:
            # Over a serial port each includes the driver's own wait for a
            # short reply (pyserial's read timeout, 50 ms): on Brian's 9700
            # every read took 50.2 ms, so a figure well above that is the
            # radio or the line, and one at it is NB.
            lines.append(f"{TIMED_READS} frequency reads: min {min(times):.1f} ms, median "
                         f"{statistics.median(times):.1f} ms, max {max(times):.1f} ms, {fails} failed "
                         f"(over a serial port each includes NB's own 50 ms read wait)")
        else:
            lines.append(f"{TIMED_READS} frequency reads: all failed")
        facts["readMs"] = statistics.median(times) if times else None
        lines.append(f"Seen on the line: {rig.echoes} echoes of NB's own frames, {rig.strays} other frames "
                     f"(transceive mode broadcasts, another controller), {rig.reader.jammed} collisions")

    def _sound(self, facts: dict) -> list[str]:
        names = self.setup.outputs()
        chosen = self.cfg.get("rigTxAudioOut") or ""
        codecs = find_codec(names)
        codec = set(codecs)
        lines = [f"IC-9700 sound device chosen in NB: {chosen or '(none)'}"
                 + ("" if not chosen or chosen in names else " - NOT among the devices listed now")]
        for n in names:
            lines.append(f"  {'*' if n == chosen else ' '} {n}{'   [USB Audio CODEC]' if n in codec else ''}")
        if not names:
            lines.append("  no output devices listed")
        if len(codecs) > 1:
            # Every Icom has one: the name proves nothing (ohscore/rig/usbpair.py).
            port = (facts.get("answered") or {}).get("port")
            pick = usbpair.radio_codec(port, codecs) if port else None
            facts["codecs"], facts["radioCodec"] = codecs, pick
            lines.append(f"{len(codecs)} USB Audio CODEC outputs - one per radio with a USB port")
            if pick:
                lines.append(f"  on the same USB hub as the radio's CI-V port: {pick}")
                if chosen and chosen != pick:
                    lines.append("  NB's choice is NOT that one: NB's tone goes to another radio")
            else:
                lines.append("  where they sit on USB does not say which is this radio's: the setup assistant's "
                             "sound device test does")
        return lines

    def _nb_settings(self) -> list[str]:
        cfg = self.cfg
        lines = []
        for k in NB_SETTINGS:
            v = cfg.get(k, self.radio.st.get(k))
            if k == "civAddress" and isinstance(v, int):
                v = f"{v:02X}h"
            elif k == "civPort":
                v = scrub(v)
            lines.append(f"{k}: {v}")
        plan = plan_from(cfg)
        conv = plan.conv
        if conv is None:
            lines.append("Upconverter: none chosen")
        else:
            lines.append(f"Upconverter: {conv.title} (TX offset {conv.tx_offset / 1e6:.3f} MHz, "
                         f"{'high-side, inverting' if conv.inverted else 'low-side'}, max drive "
                         f"{'not given' if conv.max_drive_dbm is None else f'{conv.max_drive_dbm:g} dBm'})")
        why = plan.problem()
        if why:
            lines.append(f"  NB says: {why}")
        return lines

    # ------------------------------------------------------------ 2. keyed
    def keyed_plan(self) -> dict:
        """What the keyed part would use, for its confirmation: {band,
        bandName, mainHz, rfPower, watts}. Reads through NB's link; raises
        RigError when the keyed part cannot run at all."""
        needs = self.setup.level_needs()
        if needs:
            raise RigError(needs[0]["text"])
        self.setup.link_back()
        link = self.radio.ext.link
        rf = link.call(RigSetup._rf_power)
        hz = self.radio.st.get("rigFreq")
        band = _band_of(int(hz) if hz else None)
        return {"band": band, "bandName": IF_BAND_NAMES.get(band, band or "?"), "mainHz": hz, "rfPower": rf,
                "watts": watts(band, rf)}

    def keyed(self, dummy_load: bool, confirmed: bool, progress=None) -> dict:
        """The keyed part (module docstring). `dummy_load` is the tick and
        `confirmed` the answer to the confirmation naming band and power;
        both must be True. `progress(text)` is told what is happening.
        Returns {"sections", "facts", "result": "done"|"stopped"}."""
        if dummy_load is not True:
            raise RigError(_("Tick that the IC-9700 is into a dummy load first: the keyed checks transmit"))
        if confirmed is not True:
            raise RigError(_("The keyed checks need your confirmation of the band and power first"))
        plan = self.keyed_plan()
        r = self.radio
        say = progress or (lambda _text: None)
        before = self._settings_now()
        op = float(r.st["rigTxAudioDb"])
        facts: dict = {"plan": plan, "overs": [], "before": before}
        rf = plan["rfPower"]
        lines = [f"On {plan['bandName']} ({_mhz(plan['mainHz'])}), RF POWER "
                 + ("?" if rf is None else f"{rf} ({_pct(rf)} %)")
                 + ("" if plan["watts"] is None else f", about {plan['watts']:.1f} W"),
                 f"NB's level {op:.0f} dB; PTT delay {r.st['rigPttDelayMs']} ms, tail {r.st['rigPttTailMs']} ms",
                 "Each step: level, then Po and ALC read three times after the audio reached the radio"]
        log.info("IC-9700 diagnostic: keyed part on %s, RF POWER %s", plan["bandName"], plan["rfPower"])
        stopped = False
        overs = [(_("keyed, no audio"), (None,))]
        overs += [(_("a tone, stepped"), tuple(op if x == "op" else x for x in s)) for s in SWEEPS]
        for i, (what, levels) in enumerate(overs):
            if i:
                stopped = not self._gap()
            if stopped:
                break
            say(_("Over {n} of {total}: {what}").format(n=i + 1, total=len(overs) + 1, what=what))
            got, stopped = self._sweep(levels)
            facts["overs"].append(got)
            for s in got:
                at = "no audio" if s["level"] is None else f"{s['level']:6.1f} dB"
                lines.append(f"  {at}:  Po {_list(s['po'])}   ALC {_list(s['alc'])}")
            if stopped:
                break
        tones = [s for o in facts["overs"] for s in o if s["level"] is not None]
        if tones and max(max(s["po"]) for s in tones) < PO_NONE:
            facts["noAudio"] = True
            lines.append(f"VERDICT: the radio was keyed but made no power at any level: the audio is not reaching "
                         f"it - the wrong sound device ({r.st.get('rigTxAudioOut') or '?'}; with two radios there "
                         f"are two USB Audio CODECs) or DATA MOD not USB")
        if not stopped:
            stopped = not self._gap()
        if not stopped:
            say(_("Over {n} of {total}: {what}").format(n=len(overs) + 1, total=len(overs) + 1,
                                                         what=_("timing the key-up and unkey")))
            timing, stopped = self._timing(op)
            facts["timing"] = timing
            lines += self._timing_lines(timing)
        after = self._settings_now()
        facts["after"] = after
        if after == before:
            lines.append("The radio's settings read the same after the overs as before: nothing was changed")
        else:
            for k in sorted(set(before) | set(after)):
                if before.get(k) != after.get(k):
                    lines.append(f"CHANGED during the overs: {k} was {before.get(k)}, now {after.get(k)}")
        if stopped:
            lines.append("STOPPED before the end (Stop, Halt, Escape, the time-out or a lost link)")
        log.info("IC-9700 diagnostic: keyed part %s", "stopped" if stopped else "done")
        for line in lines:
            log.info("IC-9700 diagnostic: %s", line)
        out = {"sections": [("Keyed checks (into a dummy load)", lines)], "facts": facts,
               "result": "stopped" if stopped else "done"}
        self._finished("keyed", out, f"keyed checks {out['result']}")
        return out

    def _gap(self) -> bool:
        end = time.monotonic() + GAP_S
        while time.monotonic() < end:
            if self.cancelled.is_set():
                return False
            time.sleep(0.02)
        return not self.cancelled.is_set()

    def _settings_now(self) -> dict:
        def reads(rig):
            out = {}
            for k, fn in (("usbMod", rig.read_usb_mod_level), ("rfPower", RigSetup._rf_power),
                          ("modInput", rig.read_mod_input), ("mode", rig.read_mode), ("freq", rig.read_freq)):
                try:
                    out[k] = fn(rig) if k == "rfPower" else fn()
                except RigError as e:
                    out[k] = f"unread ({e})"
            return out
        return self.radio.ext.link.call(reads)

    def _sweep(self, levels) -> tuple[list[dict], bool]:
        """One over through `levels`: [{level, po: [..], alc: [..]}], and
        whether it was stopped."""
        if self.cancelled.is_set():
            return [], True
        over = ToneOver(self.radio, levels[0])
        got: list[dict] = []
        stopped = False
        try:
            if not over.start():
                return got, True
            for i, level in enumerate(levels):
                if i:
                    if not over.time_for(SAMPLES * READ_GAP_S + 0.1):
                        log.info("IC-9700 diagnostic: %s dB left out: the over's %s s were up", level, MAX_S)
                        break
                    if not over.set_level(level):
                        stopped = True
                        break
                step = {"level": level, "po": [], "alc": []}
                for j in range(SAMPLES):
                    if j and not over.hold(READ_GAP_S):
                        stopped = True
                        break
                    m = over.meters()
                    step["po"].append(m["po"])
                    step["alc"].append(m["alc"])
                got.append(step)
                log.info("IC-9700 diagnostic: %s: Po %s, ALC %s", "no audio" if level is None else f"{level:.1f} dB",
                         step["po"], step["alc"])
                if stopped:
                    break
        finally:
            over.end()
        return got, stopped or self.cancelled.is_set()

    def _timing(self, level: float) -> tuple[dict, bool]:
        """An over at `level` that ends by itself, Po read as fast as the
        link answers from key-up until TIMING_AFTER_S after PTT off, with
        the moments NB keyed (rigCatKeyed), started the audio (tx_on_air),
        ended it and unkeyed."""
        r = self.radio
        over = ToneOver(r, level, seconds=TIMING_S)
        marks: dict = {}
        po: list[tuple[float, int]] = []
        done = threading.Event()

        def watch():
            # The engine's flags, timestamped more finely than a meter read.
            while not done.is_set():
                now = time.monotonic()
                if r.st.get("rigCatKeyed"):
                    marks.setdefault("keyed", now)
                elif "keyed" in marks:
                    marks.setdefault("unkeyed", now)
                if r.tx_on_air:
                    marks.setdefault("audio", now)
                elif "audio" in marks:
                    marks.setdefault("audioEnd", now)
                time.sleep(TIMING_POLL_S)
        w = threading.Thread(target=watch, name="ohsnb-rigdiag-timing", daemon=True)
        w.start()
        stopped = False
        try:
            r.heartbeat()
            t0 = time.monotonic()
            r._key(over.req)
            limit = t0 + TIMING_S + 3.0
            while time.monotonic() < limit:
                r.heartbeat()
                if self.cancelled.is_set():
                    stopped = True
                    break
                try:
                    po.append((time.monotonic(), r.ext.link.read_meters()["po"]))
                except RigError:
                    break
                if "unkeyed" in marks and time.monotonic() - marks["unkeyed"] > TIMING_AFTER_S:
                    break
                time.sleep(0.01)            # NB's own link poll shares the lock
        finally:
            over.end()
            done.set()
            w.join(timeout=1)
        return {"marks": marks, "po": po, "delayMs": r.st["rigPttDelayMs"], "tailMs": r.st["rigPttTailMs"]}, \
            stopped

    @staticmethod
    def _timing_lines(t: dict) -> list[str]:
        marks, po = t["marks"], t["po"]
        lines = [f"Timing over: {len(po)} Po readings"]
        if "keyed" not in marks or not po:
            return lines + ["  the over did not key, or no Po was read"]
        top = max(v for _t, v in po)
        k = marks["keyed"]

        def ms(a, b):
            return "?" if a is None or b is None else f"{1000 * (a - b):.0f} ms"
        rise = next((tt for tt, v in po if v >= top / 2 and top > 0), None)
        after_peak = [(tt, v) for tt, v in po if rise is not None and tt > rise]
        fall = next((tt for tt, v in after_peak if v < top / 10), None)
        lines += [f"  key-up answered -> audio started: {ms(marks.get('audio'), k)} (PTT delay set to "
                  f"{t['delayMs']} ms)",
                  f"  key-up answered -> Po at half its top ({top}): {ms(rise, k)}",
                  f"  audio ended -> PTT off answered: {ms(marks.get('unkeyed'), marks.get('audioEnd'))} "
                  f"(PTT tail set to {t['tailMs']} ms)",
                  f"  audio ended -> Po under a tenth: {ms(fall, marks.get('audioEnd'))}",
                  "  Po through the over (ms from key-up: Po): "
                  + ", ".join(f"{1000 * (tt - k):.0f}:{v}" for tt, v in po[:: max(1, len(po) // 40)])]
        if t["delayMs"] < DELAY_MIN_MS:
            # NB's own over starts its audio only after the delay, so it
            # cannot see the radio's switching time itself; Ray's 9700 took
            # 65 ms to half power with the audio already playing.
            lines.append(f"RECOMMEND: Delay before audio {DELAY_MIN_MS}-100 ms (Settings > Transmitter; now "
                         f"{t['delayMs']} ms). An IC-9700 takes about {RADIO_READY_MS} ms from the key to power "
                         f"(measured with the audio already playing); audio sent sooner is lost to its switching.")
        return lines

    # ------------------------------------------------------------ 3. report
    @staticmethod
    def report(*parts: dict | None) -> str:
        """The plain-text report from read_only() and keyed() results."""
        out = ["OpenHamShack QO-100 NB - IC-9700 diagnostic", "=" * 44, ""]
        for part in parts:
            if not part:
                continue
            for title, lines in part["sections"]:
                out += [title, "-" * len(title)] + list(lines) + [""]
        return "\n".join(out)


def default_path(folder: Path | None = None) -> Path:
    """Where a report is saved unless told: Documents, else the home
    folder."""
    if folder is None:
        docs = Path.home() / "Documents"
        folder = docs if docs.is_dir() else Path.home()
    return Path(folder) / time.strftime("ic9700-diagnostic-%Y%m%d-%H%M%S.txt")


def _mhz(hz) -> str:
    return f"{hz / 1e6:.6f} MHz" if hz else "?"


def _list(values) -> str:
    return " ".join(f"{v:3d}" for v in values)


def run_cli(radio_factory, path: str | None, keyed: bool, promised: bool, out=print) -> int:
    """`python3 -m ohsnb --rig-diagnostic [FILE] [--keyed …]` (ohsnb/__main__.py):
    start NB headless, run the parts asked for, write the report. The
    refusal for --keyed without the promise is made by the caller, before
    anything is opened; it is checked here again."""
    if keyed and not promised:
        out("--keyed transmits: add --i-have-a-dummy-load-and-operator-present if, and only if, the IC-9700 "
            "is into a dummy load and someone is at the radio")
        return 2
    radio = radio_factory()
    import signal
    d = RigDiagnostic(radio)
    try:
        old = signal.signal(signal.SIGINT, lambda *_a: d.cancel())
    except ValueError:              # not the main thread (tests)
        old = None
    try:
        radio.start()
        end = time.monotonic() + 15.0
        while time.monotonic() < end and radio.ext is not None and radio.state().get("rigLink") != "ok":
            radio.heartbeat()
            time.sleep(0.05)
        ro = d.read_only()
        kd = None
        if keyed:
            try:
                kd = d.keyed(True, True, progress=out)
            except (RigError, ValueError) as e:
                kd = {"sections": [("Keyed checks (into a dummy load)", [f"Not run: {e}"])], "facts": {}}
        text = RigDiagnostic.report(ro, kd)
    finally:
        radio.stop()
        if old is not None:
            signal.signal(signal.SIGINT, old)
    p = Path(path) if path else default_path()
    p.write_text(text, encoding="utf-8")
    out(f"IC-9700 diagnostic written to {p}")
    return 0
