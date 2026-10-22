"""The Pluto's chip identity: finding it, and changing it from AD9363 to
AD9364 (and back) with the operator's consent.

Why this exists. ADI ships the ADALM-Pluto telling its driver it is an
AD9363, which keeps both LOs inside 325 MHz-3.8 GHz. QO-100 NB never
notices (739 MHz and 2.4 GHz are inside); OpenHamShack Radio's 2 m, 4 m and 6 cm
are outside. On 05/10/2026 a Windows tester's stock Pluto worked in NB and
did nothing useful in HAM, which is exactly this. The silicon in a Pluto
tunes 70 MHz-6 GHz either way; the setting only tells the driver which
chip's limits to enforce, and ADI documents how to change it.

Until 05/10 the design (DESIGN-HAM.md 4.3) said the program would never
change firmware itself. Brian reversed that: the program now offers to,
showing the exact commands first, and only runs them after the operator
agrees. It changes two U-Boot environment variables, not the firmware
image, and Undo puts them back.

Sources for the commands (checked 05/10/2026):

- ADI, "Customizing the PlutoSDR" ("Updating to the AD9364"),
  https://wiki.analog.com/university/tools/pluto/users/customizing :
  firmware before v0.32: `fw_setenv attr_name compatible`,
  `fw_setenv attr_val ad9364`, `reboot`; v0.32 and later:
  `fw_setenv compatible ad9364`, `reboot`. Default login root / analog.
  The defaults are the variables being undefined (`fw_printenv attr_name`
  answers "not defined"), so Undo removes them (`fw_setenv <name>` with no
  value deletes a variable) rather than writing ad9363.
- ADI plutosdr-fw releases, https://github.com/analogdevicesinc/plutosdr-fw/releases :
  v0.39 (15/10/2023) is the newest; v0.32 is where the firmware began
  telling users whether it is an AD9364 or AD9363; v0.33 fixed
  attr_name/attr_val handling.
- Tezuka (F5OEO), https://github.com/F5OEO/tezuka_fw : extends tuning to
  47.5 MHz-6 GHz itself and is configured through its own file "based on
  standard ADI customization parameters"; its fw_version is
  "tezuka-v0.3.x", not ADI's numbering. What fw_setenv does there is not
  documented, so Tezuka - and any other firmware not numbered like ADI's -
  gets the manual steps and nothing is run.

docs/ham/pluto-identity.md has the same, with the reasoning.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field

from ohsradio.i18n import _

from . import bands

# Into the app's log file (ohscore/diag.py): every step of a fix, so a
# diagnostics zip shows what was run on the radio and what it answered.
log = logging.getLogger("ohsradio.plutofix")

DEFAULT_PASSWORD = "analog"     # ADI's factory root password (the wiki above)
DEFAULT_URI = "ip:192.168.2.1"
AD9363_RANGE = (325e6, 3.8e9)
AD9364_RX = (70e6, 6e9)
OLDEST_SUPPORTED = 26           # v0.26..v0.31: attr_name/attr_val
COMPATIBLE_FROM = 32            # v0.32..: compatible
NEWEST_KNOWN = 39               # newer than this is unknown: manual steps
REBOOT_TIMEOUT_S = 120.0
PROBE_TIMEOUT_S = 3.0


# ------------------------------------------------------------------ identity
@dataclass
class PlutoInfo:
    uri: str
    reachable: bool = False
    error: str = ""
    model: str = ""
    serial: str = ""
    fw_version: str = ""
    identity: str = ""          # ad9363 / ad9364 / ad9361, or "" if the firmware does not say
    attrs: dict = field(default_factory=dict)

    @property
    def rx_range(self) -> tuple[float, float] | None:
        if self.identity == "ad9363":
            return AD9363_RANGE
        if self.identity in ("ad9364", "ad9361"):
            return AD9364_RX
        return None


def _call_with_timeout(fn, timeout_s: float):
    """fn() on its own thread; (True, value), (False, error text) or
    (False, "timed out") - never raises, never waits past timeout_s.
    Neither libiio nor getaddrinfo can be cancelled, so a stuck call is
    left behind on a daemon thread rather than waited for."""
    box: list = []

    def run():
        try:
            box.append((True, fn()))
        except Exception as e:  # noqa: BLE001 - every failure becomes a recorded sentence
            box.append((False, f"{type(e).__name__}: {e}"))

    t = threading.Thread(target=run, daemon=True, name="ohsradio-probe")
    t.start()
    t.join(timeout_s)
    return box[0] if box else (False, f"timed out after {timeout_s:g} s")


def probe(uri: str, timeout_s: float = PROBE_TIMEOUT_S, iio_mod=None) -> PlutoInfo:
    """What the Pluto at `uri` says it is, from a fresh IIO context. Never
    raises: an unreachable radio is a PlutoInfo with the reason. It opens
    no buffers and writes nothing, so it is safe beside a running radio
    on ip:; on usb: a second context can fail while the program holds the
    radio, which is why the report prefers the open device's own record."""
    info = PlutoInfo(uri)

    def run():
        from ohscore.devices import pluto
        iio = iio_mod if iio_mod is not None else pluto.import_iio()
        ctx = pluto._open_with_timeout(iio, uri, timeout_s)
        if ctx is None:
            raise OSError(f"no IIO context at {uri}")
        attrs = dict(getattr(ctx, "attrs", {}) or {})
        if ctx.find_device("ad9361-phy") is None:
            raise OSError(f"{uri} answered but has no ad9361-phy: not a Pluto-family radio")
        return attrs

    ok, val = _call_with_timeout(run, timeout_s + 0.5)
    if not ok:
        info.error = val
        return info
    info.reachable = True
    info.attrs = {str(k): str(v) for k, v in val.items()}
    info.model = info.attrs.get("hw_model") or info.attrs.get("hw_model_variant") or ""
    info.serial = info.attrs.get("hw_serial", "")
    info.fw_version = info.attrs.get("fw_version", "")
    info.identity = (info.attrs.get("ad9361-phy,model", "") or "").lower()
    return info


def from_device(dev) -> PlutoInfo | None:
    """The same facts from the program's own open Pluto, if it has one."""
    if dev is None or getattr(dev, "kind", "") != "pluto":
        return None
    return PlutoInfo(getattr(dev, "uri", ""), reachable=True, model=getattr(dev, "model", ""),
                     serial=getattr(dev, "serial", ""), fw_version=getattr(dev, "fw_version", ""),
                     identity=getattr(dev, "identity", ""))


# ------------------------------------------------------------------ bands
def out_of_reach(identity: str, band: bands.Band) -> bool:
    """Whether an AD9363-identified Pluto cannot tune any of `band`."""
    if identity != "ad9363":
        return False
    lo, hi = AD9363_RANGE
    return band.hi < lo or band.lo > hi


def needs_ad9364(dev, band_name: str | None = None, f: float | None = None) -> bands.Band | None:
    """The band the open device cannot reach for want of the AD9364
    setting, or None. A band by name, or the band holding frequency f."""
    if dev is None or getattr(dev, "kind", "") != "pluto":
        return None
    b = bands.BY_NAME.get(band_name) if band_name else (bands.band_at(f) if f is not None else None)
    if b is None or b.deferred:
        return None
    # Only a band the AD9364 setting would bring in range: HF is out of
    # any Pluto's reach, and offering the setting for 160 m (as this did
    # until 13/10/2026) promised what it cannot do. It mattered once the
    # band row began hiding what the receiver cannot cover, keeping only
    # what this names (ohsradio/ui/widgets.py BandBar.shown).
    if b.hi < AD9364_RX[0] or b.lo > AD9364_RX[1]:
        return None
    return b if out_of_reach(getattr(dev, "identity", ""), b) else None


def band_label(b: bands.Band) -> str:
    """ "2 m", "70 cm": the name as the guide writes it."""
    return re.sub(r"(\d)(c?m)$", r"\1 \2", b.name)


def licensed_bands(licence_class: str, regime=None) -> list[bands.Band]:
    """The bands with an allocation for the class in `regime` (the licence
    in force; Ofcom's when none is given), every band if no class is set
    (the check then reports on all of them), deferred ones left out."""
    from ohscore import licences
    regime = regime or licences.ofcom
    out = []
    for b in bands.BANDS:
        if b.deferred:
            continue
        if not licence_class or licence_class not in regime.CLASSES:
            out.append(b)
            continue
        if licences.class_can_transmit(regime, licence_class, b.lo, b.hi):
            out.append(b)
    return out


# ------------------------------------------------------------------ firmware and commands
@dataclass(frozen=True)
class Plan:
    method: str                # "compatible" (v0.32+) or "attr" (before v0.32), or "" when unsupported
    reason: str                # a sentence: why this method, or why none


def firmware_plan(fw_version: str) -> Plan:
    m = re.match(r"^v0\.(\d+)\b", (fw_version or "").strip())
    if not m:
        # Two whole sentences rather than a translated "what" dropped into one.
        if fw_version:
            why = _("This Pluto runs firmware {version}, not ADI's numbered firmware, so the program does not know "
                    "what its environment commands do and will not run them. The steps below are ADI's.").format(
                version=repr(fw_version))
        else:
            why = _("This Pluto runs firmware that does not report its version, not ADI's numbered firmware, so the "
                    "program does not know what its environment commands do and will not run them. The steps below "
                    "are ADI's.")
        return Plan("", why)
    n = int(m.group(1))
    if n < OLDEST_SUPPORTED:
        return Plan("", _("Firmware {version} is older than v0.{oldest}; update it from ADI first "
                          "(the program will not change settings on firmware this old).").format(
            version=fw_version, oldest=OLDEST_SUPPORTED))
    if n > NEWEST_KNOWN:
        return Plan("", _("Firmware {version} is newer than any the program knows (v0.{newest}); "
                          "ADI's steps below are expected to work, but check their page before using them.").format(
            version=fw_version, newest=NEWEST_KNOWN))
    if n >= COMPATIBLE_FROM:
        return Plan("compatible", _("Firmware {version}: ADI's method for v0.32 and later.").format(version=fw_version))
    return Plan("attr", _("Firmware {version}: ADI's method for firmware before v0.32.").format(version=fw_version))


# (command, what it does). The reading commands come first so the log
# records what the environment held before anything changed.
_READ = ("fw_printenv attr_name attr_val compatible 2>&1 || true",
         "Shows the current chip settings (nothing is changed).")


def apply_commands(method: str) -> list[tuple[str, str]]:
    if method == "compatible":
        return [_READ, ("fw_setenv compatible ad9364",
                        "Tells the radio's boot loader to start the driver as an AD9364.")]
    if method == "attr":
        return [_READ,
                ("fw_setenv attr_name compatible", "Names the device-tree property to override (compatible)."),
                ("fw_setenv attr_val ad9364", "Sets it to AD9364.")]
    return []


def undo_commands(method: str) -> list[tuple[str, str]]:
    # Deleting is ADI's documented default state for all three; clearing
    # attr_* too on new firmware catches a radio that was set the old way
    # before its firmware was updated, which would otherwise stay AD9364.
    if method in ("compatible", "attr"):
        cmds = [_READ]
        if method == "compatible":
            cmds.append(("fw_setenv compatible", "Removes the AD9364 setting (back to ADI's default, AD9363)."))
        cmds += [("fw_setenv attr_name", "Removes the old-style override name, if any."),
                 ("fw_setenv attr_val", "Removes the old-style override value, if any.")]
        return cmds
    return []


REBOOT = ("reboot", "Restarts the radio so the setting takes effect (about 30 seconds).")


def network_host(uri: str) -> str | None:
    """The address an SSH session can use, or None for usb: and friends."""
    if uri.startswith("ip:"):
        h = uri[3:].strip()
        return h or None
    return None


def manual_steps(uri: str, plan: Plan | None = None, undo: bool = False) -> str:
    """What to type by hand: always ADI's commands for both firmware ages,
    since the reason for showing them is that the program could not tell
    which applies or could not reach the radio."""
    host = network_host(uri) or "192.168.2.1"
    target = "AD9363 (ADI's default)" if undo else "AD9364"
    lines = [f"To set the Pluto to {target} by hand:", "",
             f"1. Connect to it: ssh root@{host}   (password: analog, unless you changed it).",
             "   On Windows 10/11 'ssh' is built in; PuTTY works too.",
             "2. Type the commands for your firmware (iio_info or the Pluto's info.html shows its version):", ""]
    if undo:
        lines += ["   Firmware v0.32 or later:", "     fw_setenv compatible", "     fw_setenv attr_name",
                  "     fw_setenv attr_val", "",
                  "   Firmware before v0.32:", "     fw_setenv attr_name", "     fw_setenv attr_val", ""]
    else:
        lines += ["   Firmware v0.32 or later:", "     fw_setenv compatible ad9364", "",
                  "   Firmware before v0.32:", "     fw_setenv attr_name compatible", "     fw_setenv attr_val ad9364",
                  ""]
    lines += ["3. Restart it: reboot", "4. Wait about 30 seconds, then restart the radio in OpenHamShack Radio "
              "(Radio › Restart the radio) and use Help › Check radio… to confirm.", "",
              "Source: ADI, 'Customizing the PlutoSDR', "
              "wiki.analog.com/university/tools/pluto/users/customizing"]
    if plan is not None and plan.reason:
        lines = [plan.reason, ""] + lines
    return "\n".join(lines)


# ------------------------------------------------------------------ SSH
class AuthFailed(Exception):
    """The radio refused the password."""


class SshError(Exception):
    """Anything else: no route, refused, timed out, a command failed."""


class ParamikoSession:
    """One SSH connection to the radio through paramiko.

    Paramiko rather than the system ssh: OpenSSH reads a password only from
    a terminal, so driving it from a GUI needs sshpass (not on Windows) or
    SSH_ASKPASS tricks that differ per platform, and the Windows build has
    no console. Paramiko is pure Python on top of the cryptography package,
    in Debian as python3-paramiko and on PyPI with Windows wheels.

    Host keys: the Pluto makes new ones whenever its firmware is updated,
    and many share 192.168.2.1, so any key is accepted - for this one
    connection only. Nothing is read from or written to the user's
    known_hosts (no load_system_host_keys, no save): a stale entry there
    must not block the fix, and this connection must not leave one behind
    to break the operator's own `ssh root@192.168.2.1` later. The cost is
    no protection against an impostor on the USB link, which carries
    nothing secret except the password the operator chose to give it."""

    def __init__(self, client):
        self.client = client

    @classmethod
    def connect(cls, host: str, password: str, timeout_s: float = 10.0, port: int = 22):
        try:
            import paramiko
        except ImportError as e:
            raise SshError("The SSH library (paramiko) is missing: on Debian, sudo apt install python3-paramiko"
                           ) from e

        class _AcceptOnce(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, client, hostname, key):
                log.info("pluto ssh: accepting host key %s %s for this connection only",
                              key.get_name(), key.get_fingerprint().hex())

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(_AcceptOnce())
        try:
            client.connect(host, port=port, username="root", password=password, timeout=timeout_s,
                           auth_timeout=timeout_s, banner_timeout=timeout_s, look_for_keys=False,
                           allow_agent=False)
        except paramiko.AuthenticationException as e:
            client.close()
            raise AuthFailed(str(e)) from e
        except (paramiko.SSHException, OSError) as e:
            client.close()
            raise SshError(f"Could not connect to {host} by SSH ({e})") from e
        return cls(client)

    def run(self, cmd: str, timeout_s: float = 15.0) -> tuple[int, str]:
        try:
            _in, out, err = self.client.exec_command(cmd, timeout=timeout_s)
            text = out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")
            return out.channel.recv_exit_status(), text
        except Exception as e:  # noqa: BLE001 - socket.timeout, SSHException, EOF...
            raise SshError(f"'{cmd}' failed ({e})") from e

    def start(self, cmd: str, wait_s: float = 5.0) -> None:
        """Send a command that may never answer (reboot). It is given a few
        seconds to end the session by itself: closing the channel at once
        could hang up on the command before it has run, and dropbear sends
        the shell SIGHUP when its channel goes."""
        try:
            _in, out, _err = self.client.exec_command(cmd, timeout=wait_s)
            ch = out.channel
            end = time.monotonic() + wait_s
            while not (ch.closed or ch.exit_status_ready()) and time.monotonic() < end:
                time.sleep(0.1)
        except Exception:  # noqa: BLE001 - the link dropping is what reboot does
            pass

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ the fix
@dataclass
class Result:
    ok: bool
    message: str
    manual: str = ""             # steps to show instead, when nothing was (or could be) run
    ran: list[str] = field(default_factory=list)
    identity: str = ""


class Fixer:
    """Set the Pluto at `uri` to AD9364 (or back to AD9363) over SSH.

    Everything that touches the outside is injected - `connect(host,
    password)` returns a session with run/start/close, `identify(uri)`
    returns a PlutoInfo - so the whole sequence runs in tests against fakes,
    and on a real radio only after the operator has agreed (the dialog
    calls run() only then). The password is a local of run(): it is passed
    to connect() and to nothing else, and never logged or kept."""

    def __init__(self, uri: str, connect=ParamikoSession.connect, identify=probe,
                 reboot_timeout_s: float = REBOOT_TIMEOUT_S, poll_s: float = 3.0, settle_s: float = 8.0,
                 sleep=time.sleep, clock=time.monotonic, progress=None):
        self.uri = uri
        self.connect = connect
        self.identify = identify
        self.reboot_timeout_s = reboot_timeout_s
        self.poll_s = poll_s
        self.settle_s = settle_s
        self.sleep = sleep
        self.clock = clock
        self.progress = progress or (lambda text: None)

    def preview(self, undo: bool = False) -> tuple[PlutoInfo, Plan, list[tuple[str, str]], str]:
        """What run() would do: (info, plan, commands, why-not). Commands is
        empty when nothing will be run; why-not then says why and the caller
        shows manual_steps()."""
        target = "ad9363" if undo else "ad9364"
        host = network_host(self.uri)
        if host is None:
            return (PlutoInfo(self.uri), Plan("", ""), [],
                    _("The radio is configured as {uri}. The change is made over the Pluto's network link "
                      "(its USB Ethernet, normally ip:192.168.2.1), which this address does not use. Set the "
                      "address to ip:192.168.2.1 in Settings › Radio (Find lists it) and try again, or follow "
                      "the steps below.").format(uri=self.uri))
        info = self.identify(self.uri)
        if not info.reachable:
            return info, Plan("", ""), [], _("The radio at {uri} did not answer ({error}).").format(
                uri=self.uri, error=info.error)
        plan = firmware_plan(info.fw_version)
        if not plan.method:
            return info, plan, [], plan.reason
        if info.identity == target:
            return info, plan, [], _("This Pluto already runs as {chip}; nothing to change.").format(
                chip=target.upper())
        cmds = (undo_commands if undo else apply_commands)(plan.method) + [REBOOT]
        return info, plan, cmds, ""

    def run(self, undo: bool = False, ask_password=None) -> Result:
        """Apply (or undo) after consent. ask_password() is called at most
        once, if the default password is refused; it returns the password
        or None to give up."""
        target = "ad9363" if undo else "ad9364"
        info, plan, cmds, why = self.preview(undo)
        if not cmds:
            if info.reachable and info.identity == target:
                return Result(True, why, identity=info.identity)
            return Result(False, why, manual=manual_steps(self.uri, plan if plan.reason else None, undo),
                          identity=info.identity)
        host = network_host(self.uri)
        log.info("pluto fix: %s on %s (fw %s, identity %s)", "undo" if undo else "apply", self.uri,
                      info.fw_version, info.identity or "?")
        self.progress(_("Connecting to {host}…").format(host=host))
        try:
            sess = self._login(host, ask_password)
        except AuthFailed:
            log.info("pluto fix: password refused")
            return Result(False, _("The radio refused the password, so nothing was changed."),
                          manual=manual_steps(self.uri, None, undo), identity=info.identity)
        except SshError as e:
            log.info("pluto fix: %s", e)
            return Result(False, _("{error}. Nothing was changed.").format(error=e),
                          manual=manual_steps(self.uri, None, undo),
                          identity=info.identity)
        if sess is None:
            return Result(False, _("Cancelled: nothing was changed."), identity=info.identity)
        ran: list[str] = []
        try:
            for cmd, _what in cmds[:-1]:
                self.progress(_("Running: {command}").format(command=cmd))
                status, out = sess.run(cmd)
                ran.append(cmd)
                log.info("pluto fix: %s -> %s %s", cmd, status, out.strip()[:200])
                if status != 0:
                    return Result(False, _("'{command}' failed on the radio (exit {status}: {output}). "
                                           "The radio was not restarted.").format(
                                      command=cmd, status=status, output=out.strip()[:200]),
                                  manual=manual_steps(self.uri, None, undo),
                                  ran=ran, identity=info.identity)
            self.progress(_("Restarting the radio…"))
            sess.start(REBOOT[0])
            ran.append(REBOOT[0])
        except SshError as e:
            return Result(False, _("{error}. The radio was not restarted.").format(error=e),
                          manual=manual_steps(self.uri, None, undo),
                          ran=ran, identity=info.identity)
        finally:
            sess.close()
        return self._await(target, ran)

    def _login(self, host: str, ask_password):
        try:
            return self.connect(host, DEFAULT_PASSWORD)
        except AuthFailed:
            if ask_password is None:
                raise
        password = ask_password()
        if not password:
            return None
        return self.connect(host, password)

    def _await(self, target: str, ran: list[str]) -> Result:
        """Wait for the radio to go away and come back, then read its
        identity. A radio still answering with its old identity has not
        rebooted yet (the reboot takes a moment to start), so the old
        identity counts only once the radio has been seen gone; the new
        one counts at once, since only a reboot can produce it."""
        self.progress(_("Waiting for the radio to restart…"))
        self.sleep(self.settle_s)
        end = self.clock() + self.reboot_timeout_s
        seen_down = False
        while True:
            last = self.identify(self.uri)
            if not last.reachable:
                seen_down = True
            elif last.identity == target or seen_down:
                break
            if self.clock() >= end:
                log.info("pluto fix: no answer within %.0f s (seen down: %s)", self.reboot_timeout_s, seen_down)
                if last.reachable:
                    return Result(False, _("The settings were written, but the radio did not restart within "
                                           "{secs:.0f} s and still runs as "
                                           "{chip}. Unplug it and plug it back in, wait "
                                           "half a minute, then use Help › Check radio….").format(
                                      secs=self.reboot_timeout_s, chip=(last.identity or "?").upper()), ran=ran,
                                  identity=last.identity)
                return Result(False, _("The settings were written and the radio restarted, but it did not answer "
                                       "at {uri} within {secs:.0f} s. Unplug it, plug it "
                                       "back in, wait half a minute, then use Help › Check radio… to see "
                                       "which identity it runs as.").format(uri=self.uri, secs=self.reboot_timeout_s),
                              ran=ran)
            self.progress(_("Waiting for the radio to come back… ({why})").format(
                why=last.error or _("still restarting")))
            self.sleep(self.poll_s)
        log.info("pluto fix: back, identity %s", last.identity or "?")
        if last.identity == target:
            return Result(True, _("Done: the Pluto now runs as {chip}, which tunes {range}.").format(
                chip=target.upper(), range="325 MHz-3.8 GHz" if target == "ad9363" else "70 MHz-6 GHz"),
                          ran=ran, identity=last.identity)
        if not last.identity:
            return Result(False, _("The radio restarted, but its firmware does not report which chip it runs as, so "
                                   "the change could not be confirmed. Try 2 m once the radio is running again."),
                          ran=ran)
        return Result(False, _("The radio restarted but still reports {chip}. Its firmware may "
                               "not honour this setting; see the manual steps.").format(chip=last.identity.upper()),
                      ran=ran, identity=last.identity,
                      manual=manual_steps(self.uri, None, target == "ad9363"))


# ------------------------------------------------------------------ Help › Check radio…
@dataclass
class Check:
    label: str
    level: str      # "ok", "warn", "fail", "info"
    text: str


def check_radio(uri: str, licence_class: str, dev=None, timeout_s: float = PROBE_TIMEOUT_S,
                identify=probe) -> tuple[list[Check], PlutoInfo]:
    """The results Help › Check radio… lists. The program's own open
    device is used when it has one (a usb: Pluto may refuse a second
    context), else a fresh probe."""
    info = from_device(dev) if dev is not None and getattr(dev, "uri", None) == uri else None
    if info is None:
        info = identify(uri)
    out = [Check(_("Reachable"), "ok" if info.reachable else "fail",
                 _("{uri} answers").format(uri=uri) if info.reachable else
                 _("{uri}: {error}").format(uri=uri, error=info.error or _("no answer")))]
    if not info.reachable:
        return out, info
    out.append(Check(_("Model"), "info", info.model or _("not reported")))
    out.append(Check(_("Serial"), "info", info.serial or _("not reported")))
    plan = firmware_plan(info.fw_version)
    out.append(Check(_("Firmware"), "ok" if plan.method else "info", info.fw_version or _("not reported")))
    ident = info.identity
    if ident:
        # Two sentences: "(receive)" is words, so it cannot ride in the range.
        if ident == "ad9363":
            said = _("{chip}: tunes 325 MHz-3.8 GHz")
        else:
            said = _("{chip}: tunes 70 MHz-6 GHz (receive)")
        out.append(Check(_("Chip identity"), "warn" if ident == "ad9363" else "ok", said.format(chip=ident.upper())))
    else:
        out.append(Check(_("Chip identity"), "warn", _("not reported by this firmware")))
    if dev is not None and getattr(dev, "kind", "") == "pluto" and getattr(dev, "uri", None) == uri:
        m = getattr(dev, "m", 1)
        if m > 1:
            out.append(Check(_("FIR / sample rate"), "info",
                             _("the firmware refused the FIR: the radio runs at {radio:g} MS/s and the "
                               "program converts to {program:g} MS/s").format(radio=dev.fs * m / 1e6,
                                                                               program=dev.fs / 1e6)))
        else:
            out.append(Check(_("FIR / sample rate"), "ok", _("{rate:g} MS/s, FIR as needed").format(rate=dev.fs / 1e6)))
    else:
        out.append(Check(_("FIR / sample rate"), "info", _("known once the radio is open")))
    for b in licensed_bands(licence_class):
        if b.hf:
            continue                 # the Pluto never reaches HF; listing nine refusals says nothing new
        if out_of_reach(ident, b):
            out.append(Check(band_label(b), "fail", _("needs the AD9364 setting (out of reach as an AD9363)")))
        elif b.experimental:
            out.append(Check(band_label(b), "warn", b.experimental))
        else:
            out.append(Check(band_label(b), "ok", _("in range")))
    return out, info
