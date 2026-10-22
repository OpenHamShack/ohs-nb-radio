"""The IC-9700 setup assistant: Settings > Transmitter's "IC-9700 setup".

Ray's first CAT PTT session (12/10/2026) needed, by hand, on the radio:
SET > Connectors > MOD Input > DATA MOD = USB, a USB MOD Level at which the
ALC barely moves, the 23 cm band on MAIN with satellite mode off, CI-V
address A2; and in NB: CAT PTT on, the radio's USB Audio CODEC chosen, the
delay, the digital level. Brian asked for all of it to be found, checked
and set from NB instead, with the radio left as found on request. Three
steps, each behind its own button - nothing here runs on connect:

1. **Find** (`detect`): the CI-V address and baud rate, by asking for
   the transceiver ID (19 00) at A2 at each rate the radio offers and then
   at every other address (ohscore/rig/civ.py find_radio), and the radio's
   sound device (`find_codec`). Reads only; the dialog fills the fields in
   and Save keeps them. With more than one USB Audio CODEC - every Icom
   has one, and Ray has two radios - the name proves nothing: the one on
   the same USB hub as the CI-V port that answered is the radio's
   (ohscore/rig/usbpair.py), and when the system cannot say, nothing is
   chosen for the operator; `which_codec` then plays a tone into each in
   turn, into the dummy load, and reads Po.
2. **Check and set** (`read`, `plan`, `apply`, `restore`): reads DATA MOD,
   USB MOD Level, satellite mode, the band on MAIN and which band is
   selected, and lists "now -> will be" for each. One confirmation applies
   the list, never while the radio transmits; the values it changes are
   saved first (`rigSetupSaved`), and `restore` puts exactly those back.
   The writes go out under a SetupPermit naming only the bodies the
   operator confirmed (ohscore/rig/base.py says why), armed on this thread
   for the length of the apply.
3. **Set the audio level** (`level_set`): this one transmits - an over of
   a steady tone through the CAT PTT path itself (Radio._key, the same
   guard, permit, sound device, key-up, delay and unkey as an FT8 over),
   only after the operator has ticked that a dummy load is on. While it is
   on air the radio's Po and ALC meters (15 11, 15 13) are read and NB's
   digital level raised a step at a time from the bottom until the power
   stops rising (the knee); the level kept is the lowest step that made
   nearly all of that power. At most MAX_S seconds; Halt, Escape, the
   time-out, the watchdog or a lost link end it at once and nothing is
   stored. Every reading goes to NB's log as it is taken, and comes back
   in the result for the window to show when no level was set.

Decisions:

- **NB's level is the one adjusted, the radio's USB MOD Level left alone
  when it is sane** (20-80 %). NB's level is a slider the operator can see
  and move back; the radio's is a menu item two levels deep. Only a USB
  MOD Level at an extreme (under 20 % or over 80 %) is put on the check's
  list, to 50 %, the 9700's default [unverified], and then only with the
  same confirmation and restore as everything else. When a usual one
  still leaves NB's range unable to reach the knee, the level set's advice
  says which way to turn it by hand - never "use Check and set", which
  would leave it where it is (the first advice text did, at 50 %).
- **23 cm onto MAIN by exchanging the bands (07 B0)**, the guide's one
  command for it (CIV p.4), with MAIN selected (07 D0) so that NB's
  frequency reads and sets reach it. If satellite mode is on the guide
  gives no way to read MAIN (25 00 answers FA, CIV p.23), so satellite
  mode goes off first and MAIN is read again before exchanging; if 23 cm
  is on neither band the exchange is undone and the operator told to
  choose it on the radio.
- **The port is the assistant's while it works.** The rig link is paused
  (ohscore/rig/link.py: Windows will not open a serial port twice) and the
  engine refuses a CAT over meanwhile (Radio.rig_setup_busy).
- **The level set finds where Po stops rising, not where the ALC starts
  to move** (12/10/2026). Its first form raised the level until the ALC
  meter moved, read 0.3 s after each change, and on seeing it move at the
  first step dropped to -40 dB and read again. On Ray's IC-9700 (Windows,
  USB MOD Level 50 %, 23 cm into a dummy load) it said "the ALC moves
  even at -40 dB" and told him to set USB MOD Level to the 50 % it
  already was. Brian's own 9700 then measured it (2 m, dummy load,
  1500 Hz tone; docs/ic9700-research.md): in USB-D the ALC meter reads
  high with any audio at all - 38-72 at -40 dBFS, up to 120-160 - and
  higher at lower RF POWER, because on the 9700 the ALC is what holds
  the output to the RF POWER setting. Icom asks for the ALC "within the
  ALC zone", not at zero. So "the ALC just moves" is no criterion on this
  radio; Po is: it rises with the level and goes flat at the setting. At
  RF POWER 50 % the knee was near -28 dBFS, at 25 % near -22, and at 5 %
  (13/255) Po was already flat at -40 dBFS - Ray's case, since he drives
  an upconverter. The ALC is only a ceiling: a kept step reading above
  the zone's top (ALC_ZONE) gives way to the one under it.
- **The level only climbs, and each step waits for its own audio.** A
  level change reaches the radio only after what the sound card already
  holds has played (NB's 0.2 s queue and the card's buffer: 90 ms under
  Windows MME, PortAudio's default low latency, which PyAudio asks for),
  and the first form's 0.3 s wait was shorter than that - its "-40 dB"
  reading was of the audio before the drop. Each step now waits for the
  queue the sink reports (TxOut.tx_queued), then METER_S for the meter.
  Po is read twice a step and the larger kept, and a step reading well
  below the best so far is passed over rather than taken for the knee:
  the real meter drops out now and then (Brian's 9700 read Po 3 at a
  level whose neighbours read 26 and 70). Steps of 6 dB keep the climb
  inside MAX_S, and one probe half a step under the first step near the
  flat power narrows the knee to 3 dB.
- **The level kept is the knee, not a margin under it.** The standalone
  diagnostic kept 3 dB under the knee on Ray's 9700 (23 cm, RF POWER 59:
  Po 14, 28, 49, 74, 75, 76 at -40, -37, -34, -31, -28, -20 dBFS) and so
  ran at Po 49 of 75, a third of the power gone. The lowest level making
  KNEE_FRAC of the flat Po (-31 there) loses almost nothing, and is where
  the ALC there was just leaving its keyed baseline (5, then 13 at -31,
  39 at -28): the cross-check, reported in the result. FT8 and the other
  CAT modes are one tone at a time, so the knee is clean for them.
- **Already flat at the bottom is said plainly, and NB's level kept.**
  Then the radio is at its RF POWER setting with NB at its quietest, any
  of NB's levels makes the same power, and there is no knee to find. RF
  POWER is read (14 0A, never written: a write outside the assistant's
  shapes, which no permit can name); when it is low the advice is to
  raise it into the dummy load for the level set and put it back after;
  when it is not, the audio path is too hot, and the advice names the
  USB MOD Level as it is (Check and set changes only an extreme, so a
  usual one is turned down by hand).
- **The check is applied as shown or not at all.** `apply` reads the radio
  again and refuses if the list it would now make differs from the one the
  operator confirmed: the radio changed under the dialog.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager

import numpy as np

from ohscore import diag
from ohscore.audio import RATE
from ohscore.rig import RigError, RigTimeout, SetupPermit, civ, usbpair
from ohscore.rig.base import MOD_INPUTS

from ohsnb.i18n import _

from .extrig import CAT_MODES, IF_BAND_NAMES, IF_BANDS, MOD_OK

log = logging.getLogger("ohsnb.rigsetup")

CODEC = "usb audio codec"           # the 9700's sound device on every system (find_codec)
MME_CUT = 31                        # Windows MME cuts device names at this many characters
MOD_SANE = (51, 204)                # USB MOD Level 20-80 % of 0255: left alone
MOD_TARGET = 128                    # 50 %: what an extreme is set to

# The level set (module docstring).
LEVEL_LO, LEVEL_HI = -40.0, 0.0     # rigTxAudioDb's range: it climbs from the bottom
STEP_DB = 6.0
SETTLE_S = 0.5                      # after key-up, before the first reading: the radio's switching and inrush
METER_S = 0.25                      # per step, once the new level is playing: the radio's meter
READ_GAP_S = 0.08                   # between a step's two Po reads
MAX_S = 6.0                         # the whole over, at most
FLAT = 0.10                         # Po within 10 % of the best so far: no longer rising
KNEE_FRAC = 0.9                     # the level kept: the lowest making this much of the flat power
ALC_ZONE = 120                      # CIV p.5: ALC 0000-0120; a kept step above it gives way to the one under
PO_NONE = 5                         # of 0-255: no power at all
RF_LOW = 77                         # RF POWER under 30 % of 0255: named in the advice
CODEC_TEST_DB = -10.0              # which_codec: loud enough to make power in any setting
CODEC_TEST_S = 2.5
TONE_HZ = 1500.0
TONE_AMP = 0.9


def find_codec(names: list[str]) -> list[str]:
    """The output devices among `names` that are a radio's USB Audio CODEC
    (the TI/Burr-Brown chip the 9700 has, which every system names after
    its USB descriptor), best first. The same device by three systems:

        Windows (MME)   "Speakers (2- USB Audio CODEC )" - a number when
                        there is more than one, a stray space, truncated
                        at 31 characters
        Linux (ALSA)    "USB Audio CODEC: - (hw:2,0)", and the sound
                        server's own names for it
        macOS           "USB Audio CODEC" (some units "USB AUDIO  CODEC")

    So: case and runs of spaces ignored, the name anywhere in the string -
    or, for a name MME has cut at 31 characters, the start of it at the
    end: Ray renamed his 9700's "IC9700 Speakers", which MME lists as
    "IC9700 Speakers (USB Audio CODE" (12/10/2026). On Linux the raw hw:
    device is preferred (the one a second program cannot quietly resample
    or mix into). The order is no choice between radios: with more than
    one, rigsetup.detect asks where each sits on USB (usbpair)."""
    def hit(n: str) -> bool:
        s = " ".join(n.lower().split())
        if CODEC in s:
            return True
        return len(n) >= MME_CUT and any(s.endswith(CODEC[:k]) for k in range(len("usb au"), len(CODEC)))
    hits = [n for n in names if hit(n)]
    return sorted(hits, key=lambda n: (0 if "(hw:" in n else 1, len(n)))


def _pct(v: int) -> int:
    return round(v * 100 / 255)


def _band_of(hz: int | None) -> str:
    if hz is None:
        return ""
    for band, (lo, hi) in IF_BANDS.items():
        if lo <= hz <= hi:
            return band
    return "other"


class ToneOver:
    """One keyed over of a steady tone through the CAT PTT path: the level
    set's, and the IC-9700 diagnostic's (ohsnb/rigdiag.py). It is an over of
    the level set's kind - `source` "setup:level" with `level_set` True,
    the one tone Radio._cat_req lets through besides a send() - so it goes
    through the same guard, permit, sound device, key-up, delay and unkey
    as an FT8 over, and nothing new can key the radio. `seconds` caps it
    (the tone is that long, and the engine ends the over when it runs
    out); `level_db` None is a keyed over with no audio at all.

    Every wait feeds the watchdog (the over is the caller's own, fed as
    the window feeds an FT8 over) and returns False the moment the over
    has ended - Halt, Escape, the time-out, the watchdog, a lost link."""

    def __init__(self, radio, level_db: float | None, seconds: float = MAX_S, audio_out: str | None = None):
        self.radio = radio
        self.seconds = seconds
        n = int(seconds * RATE)
        t = np.arange(n) / RATE
        tone = (TONE_AMP * np.sin(2 * np.pi * TONE_HZ * t)).astype(np.float32)
        mode = radio.st["mode"]
        dial = radio._tx_dial(radio.st)
        self.req = {"source": "setup:level", "level_set": True, "mode": mode, "audio": tone, "start_at": 0.0,
                    "level_db": -200.0 if level_db is None else level_db, "occupied_dial": dial,
                    "occupied": radio._occupied(mode, dial, tone)}
        if audio_out:
            self.req["audio_out"] = audio_out      # which_codec: one candidate, not the saved device
        self.t0 = 0.0
        self.deadline = 0.0
        self.keyed_at: float | None = None       # when the radio answered the key-up (rigCatKeyed)
        self.on_air_at: float | None = None      # when the audio started (after the PTT delay)

    def start(self) -> bool:
        """Key, and wait until the radio is keyed, the audio is reaching
        it and it has settled. Raises what Radio._key raises (TxRefused)."""
        r = self.radio
        r.heartbeat()
        self.t0 = time.monotonic()
        self.deadline = self.t0 + self.seconds
        r._key(self.req)
        while not (r.st.get("rigCatKeyed") and r.tx_on_air):
            if self.keyed_at is None and r.st.get("rigCatKeyed"):
                self.keyed_at = time.monotonic()
            if not r.st["keyed"] or time.monotonic() - self.t0 > 2.0:
                return False
            time.sleep(0.005)
        now = time.monotonic()
        self.keyed_at = self.keyed_at or now
        self.on_air_at = now
        return self.hold(self.queued() + SETTLE_S)

    def hold(self, seconds: float) -> bool:
        r = self.radio
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if not r.st["keyed"]:
                return False
            r.heartbeat()
            time.sleep(0.01)
        return bool(r.st["keyed"])

    def queued(self) -> float:
        """How long until audio written now reaches the radio: NB's queue
        and the card's buffer (module docstring)."""
        try:
            return float(self.req["sink"].tx_queued())
        except Exception:  # noqa: BLE001 - a sink without it: assume NB's queue and Windows' default
            return 0.3

    def time_for(self, seconds: float) -> bool:
        """Whether a level change and `seconds` more fit before the cap."""
        return time.monotonic() + self.queued() + seconds < self.deadline - 0.1

    def set_level(self, level_db: float | None) -> bool:
        """Change the tone's level and wait until it is what the radio
        hears, plus METER_S for its meters."""
        self.req["sink"].gain = 0.0 if level_db is None else 10 ** (level_db / 20)
        return self.hold(self.queued() + METER_S)

    def meters(self) -> dict:
        return self.radio.ext.link.read_meters()

    def end(self) -> None:
        """Unkey now (if this over is still on the air), and wait for the
        transmit thread: the radio is unkeyed when this returns."""
        r = self.radio
        if r.st["keyed"] and r.tx_req is self.req:
            r._unkey("", None, "setup assistant test ended")
        if r.tx_thread is not None:
            r.tx_thread.join(timeout=3)


class RigSetup:
    """One run of the assistant for `radio`, with the link settings as the
    Settings dialog has them (`changes` over the saved ones, as Test
    connection does). Every call is synchronous and may take seconds: the
    dialog runs them off the GUI thread."""

    def __init__(self, radio, changes: dict | None = None):
        self.radio = radio
        self.cfg = {**radio.cfg, **(changes or {})}
        self.band = self.cfg.get("rigIfBand", "23cm")
        self.permit = SetupPermit("ohsnb setup assistant")

    # ------------------------------------------------------------ the port
    @contextmanager
    def _port(self):
        """The assistant's turn on the radio's port: NB not transmitting,
        CAT overs refused, the link paused."""
        r = self.radio
        if not self.cfg.get("civPort"):
            raise RigError(_("Set the IC-9700's CI-V port first (Settings > Transmitter)"))
        ext = r.ext
        paused = False
        # Busy before the keyed check, so no CAT over can start in between.
        r.rig_setup_busy = True
        try:
            if r.st.get("keyed"):
                raise RigError(_("NB is transmitting: the setup assistant waits until it has stopped"))
            paused = ext is not None and ext.kind == "civ"
            if paused:
                ext.link.pause()
            yield
        finally:
            if paused:
                ext.link.resume()
            r.rig_setup_busy = False

    @contextmanager
    def _rig(self):
        with self._port():
            rig = civ.CivRig(self.cfg["civPort"], int(self.cfg.get("civBaud", 115200)),
                             int(self.cfg.get("civAddress", civ.IC9700)))
            rig.open()
            try:
                yield rig
            finally:
                rig.close()

    # ------------------------------------------------------------ 1. find
    def outputs(self) -> list[str]:
        from ohscore import audio
        try:
            return [d["name"] for d in audio.list_devices() if d["outputs"] > 0]
        except Exception:  # noqa: BLE001 - PortAudio fails in many ways; then nothing is found
            log.warning("listing sound devices failed", exc_info=True)
            return []

    def detect(self, cancel=None) -> dict:
        """{"address", "id", "baud" (each None if nothing answered), "audio":
        [every USB Audio CODEC], "pick": the radio's, or None when there is
        more than one and their USB places do not say which}. Reads only."""
        port = self.cfg["civPort"]
        with self._port():
            found = civ.find_radio(port, int(self.cfg.get("civBaud", 115200)),
                                   int(self.cfg.get("civAddress", civ.IC9700)), cancel=cancel)
        codecs = find_codec(self.outputs())
        if len(codecs) == 1:
            pick = codecs[0]
        else:
            pick = usbpair.radio_codec(port, codecs) if found else None
        log.info("setup assistant: found %s; sound devices %s, the radio's %s",
                 f"{found[0]:02X}h at {found[2]} baud" if found else "nothing", codecs, pick)
        return {"address": found[0] if found else None, "id": found[1] if found else None,
                "baud": found[2] if found else None, "audio": codecs, "pick": pick}

    def which_codec(self, dummy_load: bool, candidates: list[str], progress=None) -> dict:
        """Which of `candidates` reaches the radio: a short ToneOver into
        each in turn at CODEC_TEST_DB, Po read three times. Transmits, so
        the dummy-load tick is required, as for the level set. Returns
        {"po": {name: best Po}, "radio": the one name that made power, or
        None}."""
        if dummy_load is not True:
            raise RigError(_("Tick that the IC-9700 is into a dummy load first: the sound device test transmits"))
        needs = self.level_needs()
        if needs:
            raise RigError(needs[0]["text"])
        self.link_back()
        got: dict[str, int] = {}
        for name in candidates:
            if progress is not None:
                progress(name)
            over = ToneOver(self.radio, CODEC_TEST_DB, seconds=CODEC_TEST_S, audio_out=name)
            best, stopped = 0, False
            try:
                stopped = not over.start()
                for i in range(0 if stopped else 3):
                    if i and not over.hold(READ_GAP_S):
                        stopped = True
                        break
                    best = max(best, over.meters()["po"])
            finally:
                over.end()
            if stopped:                 # Halt, Escape, Stop: no further device is tried
                break
            got[name] = best
            log.info("setup assistant: a tone into %s: Po %d", name, best)
            time.sleep(0.5)
        hits = [n for n, po in got.items() if po >= PO_NONE]
        return {"po": got, "radio": hits[0] if len(hits) == 1 else None}

    # ------------------------------------------------------------ 2. check
    def read(self) -> dict:
        with self._rig() as rig:
            return self._read(rig)

    def _read(self, rig) -> dict:
        mi = rig.read_mod_input() or {}
        sat = rig.read_satellite()
        main = None
        if not sat:
            try:
                main = rig.read_main_freq()
            except RigError:
                main = None
        return {"tx": rig.read_tx(), "dataMod": mi.get("data", ""), "usbMod": rig.read_usb_mod_level(),
                "satellite": sat, "selected": rig.read_selected(), "mainHz": main}

    def plan(self, reading: dict) -> list[dict]:
        """What the check shows: one row per item, {key, label, now, will,
        writes} - `writes` the CI-V bodies applying it sends (empty: left as
        it is). Band rows may carry `then` (decided during the apply)."""
        band = IF_BAND_NAMES[self.band]
        rows = []
        dm = reading["dataMod"]
        rows.append({"key": "dataMod", "label": _("DATA MOD (where USB-D audio comes from)"),
                     "now": dm.upper() if dm else _("unknown"),
                     "will": _("leave (includes USB)") if dm in MOD_OK else "USB",
                     "writes": [] if dm in MOD_OK else [civ.set_data_mod("usb")]})
        v = reading["usbMod"]
        sane = MOD_SANE[0] <= v <= MOD_SANE[1]
        rows.append({"key": "usbMod", "label": _("USB MOD Level"), "now": f"{_pct(v)} %",
                     "will": _("leave (NB's own level is set instead)") if sane else f"{_pct(MOD_TARGET)} %",
                     "writes": [] if sane else [civ.set_usb_mod_level(MOD_TARGET)]})
        sat = reading["satellite"]
        rows.append({"key": "satellite", "label": _("Satellite mode"), "now": _("on") if sat else _("off"),
                     "will": _("off") if sat else _("leave"), "writes": [civ.set_satellite(False)] if sat else []})
        main = _band_of(reading["mainHz"])
        if sat:
            rows.append({"key": "band", "label": _("Band on MAIN"), "now": _("unknown in satellite mode"),
                         "will": _("{band} on MAIN (bands exchanged if it is on SUB)").format(band=band),
                         "writes": [civ.EXCHANGE_BANDS], "then": True})
        elif main == self.band:
            rows.append({"key": "band", "label": _("Band on MAIN"), "now": band, "will": _("leave"), "writes": []})
        else:
            rows.append({"key": "band", "label": _("Band on MAIN"),
                         "now": IF_BAND_NAMES.get(main, _("not {band}").format(band=band)),
                         "will": _("exchange MAIN and SUB, to put {band} on MAIN").format(band=band),
                         "writes": [civ.EXCHANGE_BANDS], "then": True})
        sub = reading["selected"] == "sub"
        rows.append({"key": "selected", "label": _("Band NB tunes (selected)"), "now": "SUB" if sub else "MAIN",
                     "will": "MAIN" if sub else _("leave"), "writes": [civ.SELECT_MAIN] if sub else []})
        return rows

    def apply(self, rows: list[dict], keys=None) -> list[str]:
        """Apply the rows the operator confirmed (`keys`: the ticked ones;
        all that change by default) and return what was done, sentence by
        sentence. Refuses (RigError) while the radio or NB transmits, and if
        the radio no longer matches the check shown."""
        chosen = [row for row in rows if row["writes"] and (keys is None or row["key"] in keys)]
        if not chosen:
            return [_("Nothing to change: the IC-9700 is already set up for NB")]
        said = []
        with self._rig() as rig:
            if rig.read_tx():
                raise RigError(_("The IC-9700 is transmitting: NB changes nothing on it while it does"))
            now = self._read(rig)
            fresh = {row["key"]: row["writes"] for row in self.plan(now)}
            if any(fresh.get(row["key"]) != row["writes"] for row in chosen):
                raise RigError(_("The IC-9700's settings changed since the check: check again"))
            saved = dict(self.radio.st.get("rigSetupSaved") or {})
            want = {row["key"] for row in chosen}
            if "band" in want and now["satellite"] and "satellite" not in want:
                raise RigError(_("Satellite mode has to go off before NB can put {band} on MAIN").format(
                    band=IF_BAND_NAMES[self.band]))
            # Saved before anything is written, and only what has no
            # earlier original: a second apply must not record the first's
            # results as the radio "as it was".
            if "dataMod" in want:
                saved.setdefault("dataMod", now["dataMod"])
            if "usbMod" in want:
                saved.setdefault("usbMod", now["usbMod"])
            if "satellite" in want:
                saved.setdefault("satellite", now["satellite"])
            if "selected" in want:
                saved.setdefault("selected", now["selected"])
            saved.setdefault("port", self.cfg["civPort"])
            self._save(saved)
            bodies = [b for row in chosen for b in row["writes"]]
            self.permit.arm(bodies)
            try:
                # Satellite mode first: the band rows need it off.
                for key in ("satellite", "band", "selected", "dataMod", "usbMod"):
                    if key not in want:
                        continue
                    if rig.read_tx():
                        raise RigError(_("The IC-9700 started transmitting: NB stopped changing it ({done})").format(
                            done="; ".join(said) or _("nothing changed")))
                    said.append(self._apply_one(rig, key, saved))
            finally:
                self.permit.disarm()
                self._save(saved)
        return said

    def _apply_one(self, rig, key: str, saved: dict) -> str:
        band = IF_BAND_NAMES[self.band]
        if key == "satellite":
            rig.setup_write(civ.set_satellite(False), self.permit)
            if rig.read_satellite():
                raise RigError(_("The IC-9700 is still in satellite mode after NB switched it off"))
            return _("Satellite mode off")
        if key == "band":
            if _band_of(rig.read_main_freq()) == self.band:
                return _("{band} was already on MAIN").format(band=band)
            rig.setup_write(civ.EXCHANGE_BANDS, self.permit)
            if _band_of(rig.read_main_freq()) == self.band:
                saved["exchanged"] = not saved.get("exchanged", False)
                return _("MAIN and SUB exchanged: {band} is on MAIN").format(band=band)
            rig.setup_write(civ.EXCHANGE_BANDS, self.permit)
            return _("{band} is on neither MAIN nor SUB, so NB left the bands as they were: choose {band} on the "
                     "radio").format(band=band)
        if key == "selected":
            rig.setup_write(civ.SELECT_MAIN, self.permit)
            if rig.read_selected() != "main":
                raise RigError(_("The IC-9700 did not select MAIN"))
            return _("MAIN selected")
        if key == "dataMod":
            rig.setup_write(civ.set_data_mod("usb"), self.permit)
            got = (rig.read_mod_input() or {}).get("data", "")
            if got != "usb":
                raise RigError(_("DATA MOD reads {got} after NB set it to USB").format(got=got.upper() or "?"))
            return _("DATA MOD set to USB")
        rig.setup_write(civ.set_usb_mod_level(MOD_TARGET), self.permit)
        got = rig.read_usb_mod_level()
        if got != MOD_TARGET:
            raise RigError(_("USB MOD Level reads {got} % after NB set it").format(got=_pct(got)))
        return _("USB MOD Level set to {pct} %").format(pct=_pct(MOD_TARGET))

    def _save(self, saved: dict, step: str = "Check and set") -> None:
        with self.radio.changes_from(f"IC-9700 setup assistant: {step}"):
            self.radio.set(authorise=True, rigSetupSaved=dict(saved))

    def saved(self) -> dict:
        """What `restore` would put back: the originals, without the port."""
        return {k: v for k, v in (self.radio.st.get("rigSetupSaved") or {}).items() if k != "port"}

    def restore(self) -> list[str]:
        """Put back what `apply` changed, as it was (`rigSetupSaved`), and
        forget it. Refuses while the radio or NB transmits."""
        saved = dict(self.radio.st.get("rigSetupSaved") or {})
        todo = {k: v for k, v in saved.items() if k != "port"}
        if not todo:
            return [_("Nothing to restore: the setup assistant has not changed the radio")]
        band = IF_BAND_NAMES[self.band]
        bodies = []
        if todo.get("dataMod") in MOD_INPUTS:
            bodies.append(civ.set_data_mod(todo["dataMod"]))
        if "usbMod" in todo:
            bodies.append(civ.set_usb_mod_level(int(todo["usbMod"])))
        if todo.get("selected") == "sub":
            bodies.append(civ.SELECT_SUB)
        if todo.get("exchanged"):
            bodies.append(civ.EXCHANGE_BANDS)
        if todo.get("satellite"):
            bodies.append(civ.set_satellite(True))
        said = []
        with self._rig() as rig:
            if rig.read_tx():
                raise RigError(_("The IC-9700 is transmitting: NB changes nothing on it while it does"))
            self.permit.arm(bodies)
            try:
                if todo.get("dataMod") in MOD_INPUTS:
                    rig.setup_write(civ.set_data_mod(todo["dataMod"]), self.permit)
                    said.append(_("DATA MOD back to {src}").format(src=todo["dataMod"].upper()))
                elif "dataMod" in todo:
                    said.append(_("DATA MOD left at USB: NB could not read what it was before"))
                saved.pop("dataMod", None)
                if "usbMod" in todo:
                    rig.setup_write(civ.set_usb_mod_level(int(todo["usbMod"])), self.permit)
                    said.append(_("USB MOD Level back to {pct} %").format(pct=_pct(int(todo["usbMod"]))))
                    saved.pop("usbMod")
                # The bands and selection before satellite mode, which
                # takes them over (CIV p.23: 25 00 answers FA in it).
                if todo.get("selected") == "sub":
                    rig.setup_write(civ.SELECT_SUB, self.permit)
                    said.append(_("SUB selected again"))
                saved.pop("selected", None)
                if todo.get("exchanged"):
                    if _band_of(rig.read_main_freq()) == self.band:
                        rig.setup_write(civ.EXCHANGE_BANDS, self.permit)
                        said.append(_("MAIN and SUB exchanged back"))
                    else:
                        said.append(_("{band} is no longer on MAIN, so NB left the bands as they are").format(
                            band=band))
                saved.pop("exchanged", None)
                if todo.get("satellite"):
                    rig.setup_write(civ.set_satellite(True), self.permit)
                    said.append(_("Satellite mode on again"))
                saved.pop("satellite", None)
            finally:
                self.permit.disarm()
                self._save({} if set(saved) <= {"port"} else saved, "Put back")
        return said

    # ------------------------------------------------------------ 3. level
    def link_back(self, timeout: float = 5.0) -> None:
        """Wait (a little) for NB's link to have the port open again: a
        step that paused it (Check, Apply, the diagnostic's reads) leaves
        it reopening for a moment, and a read through it meanwhile fails
        with "not connected"."""
        link = self.radio.ext.link
        end = time.monotonic() + timeout
        while (link.rig is None or link.state != "ok") and time.monotonic() < end:
            time.sleep(0.05)

    def level_needs(self) -> list[dict]:
        """What stands between the level set and the air, as {key, text}:
        "link" (IC-9700 by CI-V not saved as the transmitter), "catPtt"
        (CAT PTT off) and "mode" (no digital mode chosen). The window
        offers a button for the last two; empty when it can start."""
        r = self.radio
        out = []
        if r.ext is None or r.ext.kind != "civ":
            out.append({"key": "link", "text": _("Save Settings with IC-9700 (CI-V) as the transmitter first: the "
                                                 "level set keys it through NB's link")})
        if not r.st.get("rigCatPtt"):
            out.append({"key": "catPtt", "text": _("'Key the IC-9700 for digital modes' is off: the level set keys "
                                                   "the radio exactly as a digital over does, so it needs it on "
                                                   "and saved")})
        if r.st["mode"] not in CAT_MODES:
            out.append({"key": "mode", "text": _("Choose a digital mode in NB first (FT8, say): the tone goes out "
                                                 "where its overs do")})
        return out

    def level_set(self, dummy_load: bool, progress=None) -> dict:
        """Transmit a steady tone through the CAT PTT path and find NB's
        digital level (module docstring). `dummy_load` is the operator's
        tick, required. `progress(step)` is called with each reading
        {level, po, alc} (a step passed over as a meter drop-out also has
        dropout: True). Returns {result: "set"|"aborted"|"advice", level
        (stored, for "set"), text, steps, usbMod, rfPower}. Raises
        RigError or engine.TxRefused (a ValueError) when it cannot start."""
        if dummy_load is not True:
            raise RigError(_("Tick that the IC-9700 is into a dummy load first: the level set transmits"))
        needs = self.level_needs()
        if needs:
            raise RigError(needs[0]["text"])
        self.link_back()
        ext = self.radio.ext
        usb_mod = ext.link.call(lambda rig: rig.read_usb_mod_level())
        rf = ext.link.call(self._rf_power)
        over = ToneOver(self.radio, LEVEL_LO)
        log.info("IC-9700 level set: keyed for a tone from %.0f dB; USB MOD Level %d %%, RF POWER %s", LEVEL_LO,
                 _pct(usb_mod), "?" if rf is None else f"{_pct(rf)} %")
        steps: list[dict] = []

        def read(level: float) -> dict | None:
            """Po twice, the larger kept (drop-outs), and the ALC; None
            when the over ended between the reads."""
            first = over.meters()
            if not over.hold(READ_GAP_S):
                return None
            second = over.meters()
            step = {"level": level, "po": max(first["po"], second["po"]), "alc": second["alc"]}
            steps.append(step)
            return step

        def said(step: dict) -> None:
            log.info("IC-9700 level set: %.0f dB: Po %d, ALC %d%s", step["level"], step["po"], step["alc"],
                     " (passed over: a meter drop-out)" if step.get("dropout") else "")
            if progress is not None:
                progress(step)

        level, aborted, timeup, flat_at = LEVEL_LO, False, False, None
        best = 0
        try:
            aborted = not over.start()
            while not aborted:
                step = read(level)
                if step is None:
                    aborted = True
                    break
                if best >= PO_NONE and step["po"] < (1 - FLAT) * best:
                    step["dropout"] = True
                elif best >= PO_NONE and step["po"] <= (1 + FLAT) * best:
                    flat_at = level          # no longer rising: the knee is behind us
                said(step)
                if flat_at is not None or level >= LEVEL_HI:
                    break
                best = max(best, step["po"])
                if not over.time_for(METER_S + READ_GAP_S):
                    timeup = True
                    break
                level = min(LEVEL_HI, level + STEP_DB)
                aborted = not over.set_level(level)
            if flat_at is not None and not aborted:
                # Half a step under the lowest step that made nearly all
                # the power: the 6 dB climb finds the knee only to within
                # 6 dB (module docstring).
                k = self._kept(steps)
                probe = k["level"] - STEP_DB / 2
                if k["level"] > LEVEL_LO and over.time_for(METER_S + READ_GAP_S):
                    if over.set_level(probe):
                        step = read(probe)
                        if step is None:
                            aborted = True
                        else:
                            step["refine"] = True
                            said(step)
                    else:
                        aborted = True
        finally:
            over.end()
        out = self._level_result(aborted, flat_at, timeup, steps, usb_mod, rf)
        log.info("IC-9700 level set: %s: %s", out["result"], out["text"])
        # For an operator who has opted in, a diagnostics upload follows
        # (ohscore/diagupload.py); keyed with no power out is a fault too.
        if out.get("noAudio"):
            diag.notable("no-power-out", "the IC-9700 level set: keyed, no power at any level")
        diag.notable("ic9700-level-set", out["result"])
        return out

    @staticmethod
    def _kept(steps: list[dict]) -> dict:
        """The step whose level is kept: the lowest that made KNEE_FRAC of
        the flat power - unless its ALC is past the zone's top, then the
        one under it (module docstring)."""
        good = sorted((s for s in steps if not s.get("dropout")), key=lambda s: s["level"])
        flat = max(s["po"] for s in good)
        kept = next(s for s in good if s["po"] >= KNEE_FRAC * flat)
        below = [s for s in good if s["level"] < kept["level"]]
        if kept["alc"] > ALC_ZONE and below:
            kept = below[-1]
        return kept

    @staticmethod
    def _rf_power(rig) -> int | None:
        """RF POWER, or None when the radio will not say (it is only ever
        named in advice)."""
        try:
            return rig.read_rf_power()
        except RigTimeout:
            raise
        except RigError:
            return None

    def _level_result(self, aborted: bool, flat_at, timeup: bool, steps: list[dict], usb_mod: int,
                      rf: int | None) -> dict:
        r = self.radio
        pct = _pct(usb_mod)
        out = {"steps": steps, "usbMod": usb_mod, "rfPower": rf}
        unchanged = _("NB's level was not changed.")
        if aborted or not steps:
            return {**out, "result": "aborted",
                    "text": _("Stopped: the over ended before the level was found. Nothing was changed.")}
        good = [s for s in steps if not s.get("dropout")]
        top = max(s["po"] for s in good)
        if top < PO_NONE:
            # Keyed (the radio answered PTT) but no power at any level, up
            # to the top: no level problem, the tone is not reaching this
            # radio. On Ray's PC it went to his other radio's CODEC.
            return {**out, "result": "advice", "noAudio": True,
                    "text": _("The IC-9700 was keyed but made no power at any of NB's levels, up to {hi:.0f} dB: the "
                              "audio is not reaching it. Either the sound device is the wrong one - NB played into "
                              "{device}, and with two radios there are two USB Audio CODECs - or DATA MOD is not "
                              "USB (Check and set). {unchanged}").format(
                        hi=steps[-1]["level"], device=self.radio.st.get("rigTxAudioOut") or "?",
                        unchanged=unchanged)}
        if flat_at is not None and flat_at <= LEVEL_LO + STEP_DB:
            # Flat from the bottom: no knee within NB's range.
            text = _("The IC-9700's power was already flat at NB's quietest level ({lo:.0f} dB, Po {po}): the radio "
                     "was at its RF POWER setting before NB's level could matter, so there is no level to find "
                     "here. {unchanged}").format(lo=LEVEL_LO, po=good[0]["po"], unchanged=unchanged)
            if rf is not None and rf < RF_LOW:
                fix = _("Its RF POWER is {rf} %, and at a low setting the 9700 holds its output down with the ALC, "
                        "so any of NB's levels makes the same power (the ALC reading high is that, not a fault). To "
                        "set the level properly, turn RF POWER up to 50 % on the radio into the dummy load, set "
                        "the level again, and then put RF POWER back to {rf} %.").format(rf=_pct(rf))
            elif usb_mod > MOD_SANE[1]:
                fix = _("The radio's USB MOD Level is {pct} %, at an extreme: use Check and set to put it at 50 %, "
                        "then set the level again.").format(pct=pct)
            elif usb_mod >= MOD_SANE[0]:
                fix = _("RF POWER is not low{rf}, so the audio reaching the radio is too hot. Its USB MOD Level is "
                        "{pct} %, in the usual range, so Check and set leaves it: turn it down on the radio (SET > "
                        "Connectors > MOD Input > USB MOD Level), to 20 % say, then set the level again.").format(
                    pct=pct, rf="" if rf is None else f" ({_pct(rf)} %)")
            else:
                fix = _("The radio's USB MOD Level is already low ({pct} %), so the audio reaching it is too hot: "
                        "turn down the computer's volume for the IC-9700 sound device, then set the level again."
                        ).format(pct=pct)
            return {**out, "result": "advice", "text": f"{text} {fix}"}
        if flat_at is not None:
            flat = max(s["po"] for s in good)
            kept = self._kept(steps)
            level = round(kept["level"], 1)
            with r.changes_from("IC-9700 setup assistant: Set level"):
                r.set(rigTxAudioDb=level)
            if MOD_SANE[0] <= usb_mod <= MOD_SANE[1]:
                why = _("The radio's USB MOD Level ({pct} %) was left as it is: it is in the usual range, and NB's "
                        "level is the one you can see and move.").format(pct=pct)
            else:
                why = _("The radio's USB MOD Level is {pct} %, at an extreme: Check and set offers to put it at "
                        "50 %; run this again after it.").format(pct=pct)
            return {**out, "result": "set", "level": level,
                    "text": _("The IC-9700's power stopped rising by {at:.0f} dB (Po {flat}). NB's digital level is "
                              "now {level:.0f} dB, the lowest level that made nearly all of that power (Po {po}); "
                              "the ALC read {alc} there and {base} at the bottom. Any lower gives away power, and "
                              "any higher only drives the ALC harder. {why}").format(
                        at=flat_at, flat=flat, level=level, po=kept["po"], alc=kept["alc"], base=steps[0]["alc"],
                        why=why)}
        if timeup:
            return {**out, "result": "advice",
                    "text": _("The IC-9700's power was still rising at {at:.0f} dB when the {secs:.0f} s were up. "
                              "{unchanged} Run it again.").format(at=steps[-1]["level"], secs=MAX_S,
                                                                  unchanged=unchanged)}
        if usb_mod < MOD_SANE[0]:
            fix = _("The radio's USB MOD Level is {pct} %, at an extreme: use Check and set to put it at 50 %, then "
                    "set the level again.").format(pct=pct)
        else:
            fix = _("The radio's USB MOD Level is {pct} %: raise it on the radio (SET > Connectors > MOD Input > USB "
                    "MOD Level), or the computer's volume for the IC-9700 sound device, then set the level again."
                    ).format(pct=pct)
        return {**out, "result": "advice",
                "text": " ".join((_("The IC-9700's power was still rising at NB's full level."), fix, unchanged))}
