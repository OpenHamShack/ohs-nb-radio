"""An IC-9700 (or any rig Hamlib knows) as QO-100 NB's uplink transmitter.

Ray receives QO-100 with NB and a Pluto but transmits with an IC-9700 on
23 cm into an upconverter to 13 cm. For voice NB never keys that radio
(PTT stays on the radio). Until 12/10/2026 it could not key it at all,
by design, ohscore/rig enforcing that with a command whitelist; on
12/10/2026 Brian decided NB may key it by CAT PTT for its own digital-mode
overs, as WSJT-X does (`CatPtt`, below, and the `rigCatPtt` setting, off
by default). Beyond that, what NB does is what a transceiver's second VFO would: put
the 9700 where the dial says, follow it when its knob is turned, show on
the scope where it is aimed and where it actually landed, correct it, and
measure its level against the beacon. This module is the QO-100 half of
that; the protocol drivers and the polling thread are ohscore/rig (shared,
so OpenHamShack Radio can use them for CAT).

Frequencies (DESIGN.md vocabulary, plus the rig's):

    ul       = dl - 8089.5 MHz                      (the transponder)
    rig      = ul - LO          low-side mixing     (IF + LO = uplink)
    rig      = LO - ul          high-side mixing    (LO - IF = uplink; inverted)

The LO and the side are the IC-9700 path's converter, `rigTxConverter`
(ohsnb/converters.py): a down-converter, inverting when it is high-side.
    sent rig = rig(ul(txDial) + rigTxCorr)

`rigTxCorr` is the 9700 path's own correction (the 9700's reference and
the upconverter's LO error together) and is kept apart from `txCorr`,
which is the Pluto's: two transmitters, two errors, and switching between
them must not carry one's correction to the other.

High-side mixing inverts the spectrum: the 9700's USB goes up as LSB and
turning its knob up moves the uplink down. Everything here works in
on-air terms, converting at this boundary only (`on_air_mode`, `ul_of`).

Decisions:

- **The TX marker is where the 9700 is aimed**: NB's transmit dial. When
  NB tunes, the 9700 is set to match; when the 9700's knob moves, NB's
  transmit dial moves with it. With `rigRxFollows` (the default) the
  receive dial goes too and split is cleared - one dial, as on a
  transceiver, so turning the 9700 is also how Ray listens around; with it
  off, the 9700 drives split's transmit dial and NB's receive stays put.
- **NB's mode follows the 9700's sideband** (USB, LSB, CW, on air), on a
  change only, so a digital mode chosen in NB to decode (FT8 through the
  9700's USB-D) is left alone. NB sets the 9700's mode in one case only:
- **FM is switched to SSB** (`rigFmToSsb`, on by default; Brian, 08/10).
  The narrowband transponder carries no FM, and a 9700 left in FM from a
  repeater or a local net is the usual reason an over goes nowhere. When
  the radio is found in FM, NB puts it in the sideband that goes up as USB
  (LSB through an inverting upconverter) and says so. Never while it is
  transmitting - the switch waits for the over to end - and only out of
  FM: AM, DV and the data modes are the operator's business, and judge()
  still warns about them.
- **Corrections between overs, never during one.** Icom's CI-V reference
  does not say whether a frequency set while transmitting is applied, and
  rigctld does not either (docs/ic9700-research.md); satellite programs
  retune in satellite mode, which is not how Ray uses the radio. So TX
  lock measures during the over and the correction goes to the 9700 as
  soon as it is back on receive. A correction is taken from a carrier
  (the 9700 in CW, key down) or from an over NB keyed itself by CAT PTT:
  NB rendered that audio, so TX lock matches it as it matches the Pluto's
  baseband, wherever in the passband its tones are (Radio._rig_keyed; until
  0.1.17 these overs were looked for by the band edge and never corrected,
  and Ray's FT8 stayed 840 Hz off). Speech, or a digital mode another
  program sends with the radio's own PTT, places the signal only to a
  couple of hundred hertz by the edge of its band: shown on the scope,
  never applied, because those tones are wherever that program put them.
- **The transmit guard is advisory** for the radio's own PTT. NB judges
  where the 9700 is aimed exactly as it judges its own transmitter, and
  says so loudly - but it cannot stop the 9700 being keyed by hand, and
  the warning says that too. For an over NB keys itself (CAT PTT) it is a
  real guard, see below.
- **CAT PTT, digital modes only** (Brian, 12/10/2026; `CatPtt`). With
  `rigCatPtt` on, an over from Engine.send() in one of CAT_MODES - the
  desktop's Enable TX and the store form's automatic transmit for the
  slotted modes, a sent line in PSK, RTTY or CW, a KG-STV picture from the
  Beacon view (from 0.1.18, whatever NB's own mode) - keys the 9700 by CAT,
  with NB's rendered audio going to the radio's USB sound device
  (`rigTxAudioOut`) and the radio in USB-D (LSB-D through an inverting
  upconverter). PTT, a voice memory, FreeDV, SSTV and HSmodem never key it:
  speech stays on the radio's own PTT, and the long or experimental modes
  were left out until someone asks. CW lines go as an audio tone in USB-D,
  so the radio stays in the data mode and nothing writes CW to it. The
  over passes every check NB's own transmitter does - licence, band plan
  and beacons for the occupied band measured from the audio, the
  time-out, the watchdog, a re-check whenever the dial, mode or setting
  changes - plus the 9700's: link up, on the transmit frequency, where it
  is aimed judged as it will be (USB-D), and its MOD Input taking USB
  audio when that can be read. Sequence: data mode (re-asserted, with a
  warning, if the operator changed it on the radio since - never fought
  between overs), key, read the transmit state back, `rigPttDelayMs`, the
  audio; then the audio drained and stopped, `rigPttTailMs`, unkey, read
  back. Halt, Enable TX off, a mode change, the setting off, app exit and
  the time-out unkey at once (no tail). A lost link cannot be unkeyed or
  confirmed: NB says so, and unkeys the radio as soon as it answers again.
- **The data variant for digital modes** (Brian, 12/10/2026). With
  `rigCatPtt` on, choosing one of CAT_MODES in NB asks for the 9700 in
  USB-D, once, between overs; going back to USB or LSB in NB, after NB
  put it in data, asks for plain SSB. One-shot requests, not a level NB
  holds the radio at, so a change made on the radio is left alone until
  the next key-up re-asserts it.
- **Receive audio while the 9700 transmits** is muted by default (Ray's
  microphone hears the speaker), or lowered, or left, as the operator
  chooses. Only the audio: the scopes, beacon lock and TX lock keep
  receiving. It is a factor applied on top of the operator's own Mute and
  volume, so it never changes them; it lifts `rttSec` + 0.3 s after the
  9700 unkeys, when the tail of his own downlink has come back, and at once
  if the link is lost (an unknown transmit state must not leave him deaf).
"""
from __future__ import annotations

import time

from ohscore import diag
from ohscore.converters import Converter
from ohscore.rig import PttPermit, RigError, make_rig
from ohscore.rig.link import RigLink

from ohsnb.i18n import _

from . import bandplan
from . import converters as nbconv

# The IC-9700's transmit ranges per band, Hz: the EUR version's
# (docs/ic9700-research.md) - UK radios are EUR, and it is the narrower
# set, so a plan that passes here works on any version but Italy's.
IF_BANDS = {
    "2m": (144_000_000.0, 146_000_000.0),
    "70cm": (430_000_000.0, 440_000_000.0),
    "23cm": (1_240_000_000.0, 1_300_000_000.0),
}
IF_BAND_NAMES = {"2m": "2 m", "70cm": "70 cm", "23cm": "23 cm"}

UNMUTE_AFTER = 0.3      # s after the round trip before receive audio comes back


class UplinkPlan:
    """The upconverter: where the 9700 must be for an uplink, and back.
    `conv` is the IC-9700 path's converter (ohsnb/converters.py,
    `rigTxConverter`), or None while none is chosen. Low-side mixing (IF +
    LO = uplink) is a down-converter that does not invert; high-side
    (LO - IF = uplink) is an inverting one. The maths are the shared
    model's (ohscore/converters.py) and the same as up to 0.1.6, when the LO
    and side were settings of their own (upconverterLo, upconverterSide)."""

    def __init__(self, conv: Converter | None, band: str = "23cm"):
        self.conv = conv
        self.band = band

    @property
    def lo(self) -> float | None:
        return None if self.conv is None else self.conv.tx_offset

    @property
    def inverted(self) -> bool:
        return self.conv is not None and self.conv.inverted

    def rig_hz(self, ul_hz: float) -> float:
        return self.conv.radio(ul_hz, tx=True)

    def ul_of(self, rig_hz: float) -> float:
        return self.conv.air(rig_hz, tx=True)

    def on_air_mode(self, rig_mode: str) -> str:
        return self.conv.air_mode(rig_mode) if self.conv is not None else rig_mode

    def problem(self) -> str:
        """'' if every frequency of the NB uplink can be reached on the
        chosen band; else the sentence saying why not."""
        if self.conv is None:
            return _("Choose your upconverter (Settings > Transmitter, from the list in Settings > Converters): "
                     "OpenHamShack QO-100 NB cannot work out where to put the IC-9700 without its local oscillator")
        if not self.conv.transmits:
            return _("{converter} is receive only: mark it TX only or RX/TX in Settings > Converters to "
                     "transmit through it").format(converter=self.conv.title)
        lo_hz, hi_hz = self.conv.radio_range(bandplan.UL_LO, bandplan.UL_HI, tx=True)
        b_lo, b_hi = IF_BANDS[self.band]
        if lo_hz < b_lo or hi_hz > b_hi:
            how = "LO + IF" if not self.inverted else "LO - IF"
            return _("With a {lo:.3f} MHz LO ({how} = uplink), the uplink "
                     "{ul_lo}-{ul_hi} MHz needs the IC-9700 on "
                     "{rig_lo:.3f}-{rig_hi:.3f} MHz, outside its {band} range "
                     "({band_lo:.0f}-{band_hi:.0f} MHz). Check the LO, and whether the mixer is low- or "
                     "high-side").format(
                lo=self.lo / 1e6, how=how, ul_lo=bandplan.mhz(bandplan.UL_LO, 1), ul_hi=bandplan.mhz(bandplan.UL_HI, 1),
                rig_lo=lo_hz / 1e6, rig_hi=hi_hz / 1e6, band=IF_BAND_NAMES[self.band],
                band_lo=b_lo / 1e6, band_hi=b_hi / 1e6)
        return ""

    def in_band(self, rig_hz: float) -> bool:
        b_lo, b_hi = IF_BANDS[self.band]
        return b_lo <= rig_hz <= b_hi


def plan_from(cfg: dict) -> UplinkPlan:
    return UplinkPlan(nbconv.rig_converter(cfg), cfg.get("rigIfBand", "23cm"))


def check_settings(st: dict) -> None:
    """Raise ValueError if the transmitter settings cannot work (Settings'
    save calls this through Radio._adjust_set)."""
    if st.get("txRadio", "sdr") == "sdr":
        return
    why = plan_from(st).problem()
    if why:
        raise ValueError(why)


DIGITAL = {"ft8", "ft4", "q65", "js8", "psk31", "psk63", "psk125", "rtty", "freedv", "sstv", "kgstv"}
# The modes NB keys the IC-9700 for by CAT (module docstring): its
# Enable TX modes, its text lines, and KG-STV pictures (Brian, 12/10/2026:
# "exactly as other digital modes"). Not FreeDV (speech), SSTV or HSmodem.
CAT_MODES = ("ft8", "ft4", "q65", "js8", "psk31", "psk63", "psk125", "rtty", "cw", "kgstv")
# What a MOD Input setting means for NB's audio: reaches the modulator, or not.
MOD_OK = ("usb", "mic,usb")
OWED_RETRY_S = 5.0      # between tries of an unconfirmed unkey once the link is back (not a toast a poll)


def mod_input_problem(src: str) -> str:
    """'' if transmit audio from the radio's USB sound device reaches its
    modulator with MOD Input `src` (as the link reads it; '' unknown);
    else why not."""
    if not src or src in MOD_OK:
        return ""
    return _("The IC-9700 takes USB-D audio from {src} (SET > Connectors > MOD Input > DATA MOD): set it to USB, "
             "or NB's audio will not reach the transmitter").format(src=src.upper())


class CatPtt:
    """CAT PTT for NB's digital overs (module docstring). Holds the one
    PttPermit the drivers accept, armed only on the engine's transmit
    thread between key-up and key-down. Every call here except
    `unkey_now` runs on that thread."""

    def __init__(self, ext: "ExternalTx"):
        self.ext = ext
        self.permit = PttPermit("ohsnb digital over")
        self.keyed = False          # NB keyed it and has not seen it unkey
        self.owed = False           # an unkey NB could not confirm: sent again once the link answers
        self.owed_tried = 0.0
        self.t_cmd = 0.0            # when the last key or unkey command went, for the log's confirm times

    def want_mode(self) -> tuple[str, bool]:
        """The rig mode for a digital over: the sideband that goes up as USB, DATA on."""
        return self.ext.plan.on_air_mode("usb"), True

    def key_up(self, start_at: float, halted) -> None:
        """Data mode, key, confirm, then wait out the PA delay (and, for a
        timed over keyed early, until its start). Raises RigError, after
        which the engine's key-down unkeys."""
        r = self.ext.radio
        link = self.ext.link
        want = self.want_mode()
        was = (link.mode, link.data)
        got = link.set_data_mode_now(*want)
        if got != want:
            raise RigError(_("The IC-9700 would not go to {mode}-D (it reports {got}{data}): not keyed").format(
                mode=want[0].upper(), got=got[0].upper(), data="-D" if got[1] else ""))
        if was[0] and was != want:
            r.toast(_("The IC-9700 was in {was}: NB put it back in {mode}-D for this over").format(
                was=was[0].upper() + ("-D" if was[1] else ""), mode=want[0].upper()), "warn")
        self.permit.arm()
        self.keyed = True
        t_key = self.t_cmd = time.monotonic()
        if not link.ptt(True, self.permit):
            r.log.warning("IC-9700 keyed by CAT did not read back as transmitting (%.0f ms)",
                          1000 * (time.monotonic() - t_key))
            raise RigError(_("The IC-9700 did not go to transmit when NB keyed it"))
        r._status(rigCatKeyed=True)
        # The read-back straight after the command is the radio's own word
        # that it is transmitting; the link's poll (rigKeyed, report())
        # then sees it again, and says when.
        r.log.info("IC-9700 keyed by CAT for a %s over: it read back transmitting %.0f ms after the command",
                   r.st["mode"], 1000 * (time.monotonic() - t_key))
        until = max(t_key + r.st["rigPttDelayMs"] / 1000.0, time.monotonic())
        wall_wait = (start_at - time.time()) if start_at else 0.0
        until = max(until, time.monotonic() + wall_wait)
        while time.monotonic() < until and not halted():
            time.sleep(min(0.01, until - time.monotonic()))

    def key_down(self, halted: bool) -> None:
        """After the audio has stopped: the tail (not after an emergency
        unkey), then unkey and confirm."""
        try:
            if not self.keyed:
                return
            if not halted:
                tail = self.ext.radio.st["rigPttTailMs"] / 1000.0
                if tail > 0:
                    time.sleep(tail)
            self.unkey_now()
        finally:
            self.permit.disarm()
            self.ext.radio._status(rigCatKeyed=False)

    def unkey_now(self) -> bool:
        """Unkey and read back; True when the radio says it is on receive.
        Any thread (the permit allows unkeying from anywhere)."""
        r = self.ext.radio
        t = self.t_cmd = time.monotonic()
        try:
            on = self.ext.link.ptt(False, self.permit)
        except RigError as e:
            r.log.warning("IC-9700 unkey by CAT failed after %.0f ms: %s", 1000 * (time.monotonic() - t), e)
            self.owed = True
            r.toast(_("Could not unkey the IC-9700 ({error}): NB cannot confirm it stopped transmitting - "
                      "check the radio, and release it there if it is still on the air").format(error=e), "error")
            return False
        if on:
            self.owed = True
            r.toast(_("The IC-9700 still says it is transmitting after NB unkeyed it: release it on the radio"),
                    "error")
            return False
        self.keyed = self.owed = False
        r.log.info("IC-9700 unkeyed by CAT: it read back receiving %.0f ms after the command",
                   1000 * (time.monotonic() - t))
        return True


def judge(on_air: str, dl: float, nb_mode: str, data: bool, lo: float, hi: float) -> str:
    """Why NB would not transmit where the external radio is aimed at `dl`
    in `on_air` mode, or ''. `lo`/`hi` are NB's transmit audio edges,
    taken as the radio's (NB cannot read its transmit bandwidth). A
    digital mode sent through the radio's sound card - its DATA mode on,
    or NB itself set to a digital mode to decode it - is judged as
    digital, by where the passband reaches but not by its width: the
    program sending it places its tones anywhere in that passband."""
    if on_air in ("am", "fm", "wfm", "dv", "dd"):
        return f"{on_air.upper()} is not used on the narrowband transponder"
    if on_air in ("cw", "cw-r"):
        return bandplan.tx_blocked(dl - 50.0, dl + 50.0, "cw")
    lower = on_air in ("lsb", "rtty-r")
    a, b = (dl - hi, dl - lo) if lower else (dl + lo, dl + hi)
    if on_air.startswith("rtty") or data or nb_mode in DIGITAL:
        return bandplan.tx_blocked(a, b, nb_mode if nb_mode in DIGITAL else "rtty", widths=False)
    if on_air in ("usb", "lsb"):
        return bandplan.tx_blocked(a, b, on_air)
    return f"the radio's mode ({on_air}) is not one OpenHamShack QO-100 NB can judge"


class ExternalTx:
    """The radio's side of an external transmitter: owns the RigLink, and
    turns what it reads into NB state. Created by Radio.start() when
    `txRadio` is not "sdr"; every method that touches engine state takes the
    radio's lock (they run on the link's thread)."""

    def __init__(self, radio):
        self.radio = radio
        cfg = radio.cfg
        self.plan = plan_from(cfg)
        self.kind = cfg["txRadio"]
        self.keyed = False
        self.unmute_at = 0.0
        self.hold = False          # the knob took the 9700 off the transponder: leave it be
        self.last_mode = ""
        self.over_errs: list[tuple[str, float]] = []
        self.link = RigLink(lambda: make_rig(self.kind, cfg), self.want, self.report,
                            poll_s=cfg["rigPollMs"] / 1000.0, may_set_keyed=False,
                            want_mode=self.want_mode, name="ohsnb-rig",
                            read_mod_input=bool(radio.st.get("rigCatPtt")))
        self.cat = CatPtt(self)
        self.data_set = False      # NB asked for the data variant (so going back to SSB asks for plain)

    def start(self):
        problem = self.plan.problem()
        self.radio._status(rigLink="connecting", rigError=problem, rigKeyed=False, rigCatKeyed=False, rigModInput="")
        self.link.start()
        self.nb_mode(self.radio.st["mode"])

    def nb_mode(self, mode: str) -> None:
        """NB's mode changed (or the link started): ask for the data
        variant on entering a CAT mode, plain SSB on going back to USB or
        LSB after NB put it in data - once each, between overs."""
        if not self.radio.st.get("rigCatPtt") or self.plan.problem():
            return
        if mode in CAT_MODES:
            self.link.request_data_mode(*self.cat.want_mode())
            self.data_set = True
        elif mode in ("usb", "lsb") and self.data_set:
            self.link.request_data_mode(self.plan.on_air_mode(mode), False)
            self.data_set = False

    def stop(self):
        if self.cat.keyed:
            # App exit (Radio.stop has already ended any over): one last
            # unkey while the link still holds the port.
            self.cat.unkey_now()
        self.link.stop()
        was = self.keyed
        self.keyed = False
        self.unmute_at = 0.0
        if was:
            self.radio._rig_unkeyed(apply=False)
        self.radio._status(rigLink="off", rigKeyed=False)

    # ------------------------------------------------------------ to the rig
    def want(self) -> int | None:
        r = self.radio
        if self.plan.problem() or self.hold:
            return None
        with r.lock:
            ul = bandplan.ul(r.st["txDial"]) + r.st["rigTxCorr"]
        f = self.plan.rig_hz(ul)
        if not self.plan.in_band(f):
            return None
        return int(round(f))

    def want_mode(self, rig_mode: str) -> str | None:
        """The rig mode to put the 9700 in, given the one it is in: the
        sideband that goes up as USB when it is in FM, else None."""
        if rig_mode != "fm" or not self.radio.st["rigFmToSsb"]:
            return None
        return self.plan.on_air_mode("usb")

    def aim_dl(self, rig_hz: float) -> float:
        """Where a signal from the 9700 on rig_hz is meant to land, with the
        correction taken out: the downlink NB's transmit dial shows."""
        return bandplan.dl(self.plan.ul_of(rig_hz) - self.radio.st["rigTxCorr"])

    # ------------------------------------------------------------ from the rig
    def report(self, snap: dict) -> None:
        r = self.radio
        link = snap["link"]
        problem = self.plan.problem()
        err = problem or (snap.get("error") if link != "ok" else "")
        if snap.get("refused") is not None:
            err = _("The IC-9700 refused {mhz:.6f} MHz ({error}). Is the "
                    "{band} band on MAIN?").format(mhz=snap["refused"] / 1e6, error=snap.get("error"),
                                                   band=IF_BAND_NAMES[self.plan.band])
        if snap.get("mode_to"):
            r.toast(_("The IC-9700 was in FM, which the narrowband transponder does not carry: "
                      "switched it to {mode}").format(mode=snap["mode_to"].upper()), "info")
        elif snap.get("mode_refused"):
            r.toast(_("The IC-9700 is in FM and refused a change to {mode} "
                      "({error}): switch it to SSB on the radio").format(
                mode=snap["mode_refused"].upper(), error=snap.get("error")), "warn")
        if snap.get("data_mode_to") and snap.get("data_mode_from") != snap["data_mode_to"]:
            m, d = snap["data_mode_to"]
            r.toast(_("The IC-9700 is now in {mode} for {nb}").format(
                mode=m.upper() + ("-D" if d else ""), nb=r.st["mode"].upper()), "info")
        elif snap.get("data_mode_refused"):
            m, d = snap["data_mode_refused"]
            r.toast(_("The IC-9700 refused {mode} ({error}): set it on the radio").format(
                mode=m.upper() + ("-D" if d else ""), error=snap.get("error")), "warn")
        self.link.read_mod_input = bool(r.st.get("rigCatPtt"))
        f = snap.get("freq")
        status = {"rigLink": link, "rigError": err or ""}
        if r.st.get("rigLink") == "ok" and link in ("lost", "error"):
            # Answering, then not: a fault for the opt-in diagnostics upload.
            diag.notable("rig-link-lost", err or link)
        mi = snap.get("modInput")
        status["rigModInput"] = (mi.get("data" if snap.get("data") else "plain") or "") if mi else ""
        if (link == "ok" and self.cat.owed and not r.st["keyed"]
                and time.monotonic() - self.cat.owed_tried > OWED_RETRY_S):
            self.cat.owed_tried = time.monotonic()
            # An unkey NB could not confirm (a lost link mid-over): the
            # radio answers again, so tell it now. On the link's thread,
            # outside its lock (report is called after the transaction).
            if self.cat.unkey_now():
                r.toast(_("The IC-9700 link is back: NB unkeyed the radio"), "info")
        if link == "ok" and f is not None and not problem:
            status["rigFreq"] = float(f)
            aim = self.aim_dl(f)
            status["rigAimDl"] = aim
            if snap.get("moved"):
                self._knob(aim)
        elif link == "ok" and f is not None:
            status["rigFreq"] = float(f)
        mode = snap.get("mode") or ""
        on_air = self.plan.on_air_mode(mode) if mode else ""
        status["rigMode"] = on_air
        if on_air and on_air != self.last_mode:
            self.last_mode = on_air
            self._follow_mode(on_air)
        r._status(**status)
        keyed = bool(snap.get("keyed")) and link == "ok"
        if keyed != self.keyed:
            self.keyed = keyed
            # rigKeyed: the poll's view, which TX lock and the receive mute
            # follow. For NB's own over, how long after the command; for a
            # hand-keyed one, that the radio went to transmit at all.
            since = (f", {1000 * (time.monotonic() - self.cat.t_cmd):.0f} ms after NB's CAT command"
                     if self.cat.t_cmd and link == "ok" else "")
            self.cat.t_cmd = 0.0         # one command, one confirmation: a later hand-keyed over is not timed
            r.log.info("IC-9700 link reports %s (rigKeyed)%s", "transmitting" if keyed else
                       ("receiving" if link == "ok" else f"nothing: link {link}"), since)
            if keyed:
                r._rig_keyed()
                self.unmute_at = 0.0
            else:
                lost = link != "ok"
                # The tail of his own downlink is still on its way down.
                self.unmute_at = 0.0 if lost else time.monotonic() + r.st["rttSec"] + UNMUTE_AFTER
                r._rig_unkeyed(apply=not lost)
                if lost:
                    r.toast(_("Lost the IC-9700 link while it was transmitting: receive audio is back on, "
                              "and NB no longer knows whether it is transmitting"), "warn")
        r._rig_guard(snap.get("data", False))
        # The transmit card's standing warning while it transmits there
        # (Engine.tx_warn). Up to 0.1.9 a toast, once per over: it went
        # with the toast's few seconds while the radio carried on.
        # Not for an over NB keyed itself: its guard passed it, re-checks it,
        # and can unkey it, so "NB cannot unkey it" would be untrue.
        why = r.st.get("rigTxBlocked") if self.keyed and not self.cat.keyed else ""
        if why:
            r.tx_warn("rig-aim", f"The IC-9700 is transmitting where NB would not: {why}. NB cannot unkey it - "
                                 "release PTT on the radio", "error")
        else:
            r.tx_clear("rig-aim")

    def _knob(self, aim: float) -> None:
        r = self.radio
        if not (bandplan.DL_LO <= aim <= bandplan.DL_HI):
            self.hold = True
            return
        self.hold = False
        s = r.st
        xit = s["xit"] if s["xitOn"] else 0.0
        dial = round(aim - xit, 0)
        try:
            if s["rigRxFollows"]:
                r.set(vfo=dial, split=False)
            else:
                r.set(split=True, txVfo=dial)
        except ValueError:
            self.hold = True

    def _follow_mode(self, on_air: str) -> None:
        r = self.radio
        want = {"usb": "usb", "lsb": "lsb", "cw": "cw", "cw-r": "cw"}.get(on_air)
        if want and r.st["mode"] in ("usb", "lsb", "cw") and r.st["mode"] != want:
            try:
                r.set(mode=want)
            except ValueError:
                pass

    def released(self) -> None:
        """The operator moved NB's dial: if the knob had taken the 9700 off
        the transponder, NB's dial is in charge again."""
        self.hold = False

    # ------------------------------------------------------------ audio
    def audio_gain(self, s: dict) -> float:
        if not (self.keyed or time.monotonic() < self.unmute_at):
            return 1.0
        how = s["rigAudio"]
        if how == "mute":
            return 0.0
        if how == "lower":
            return 10 ** (-s["rigAudioLowerDb"] / 20)
        return 1.0
