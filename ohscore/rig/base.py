"""What every external-rig driver offers, and the byte pipe CI-V runs over.

An external rig is a radio the program does not own: it reads where the
rig is tuned and whether it is transmitting, and may set its frequency and
put it in USB or LSB - and, since 12/10/2026, key it for a digital-mode
over under a permit (below). Nothing else. QO-100 NB uses one to follow
an IC-9700 used as the QO-100 uplink transmitter; OpenHamShack Radio may use the
same drivers for CAT later.

The interface is deliberately narrow. The more a driver can do, the more
a bug can do: there is no power, no menu write outside the setup
assistant's confirmed few (below), and the one mode write
reaches only USB and LSB (`set_ssb`), and each driver checks every command
it is about to send against a whitelist of exactly these
(`ForbiddenCommand` otherwise), so not even a programming error elsewhere
can change the radio's power through this package.

PTT, and why it is here at all. Until 12/10/2026 there was none: the
package could not key a radio, by design, and NB told the operator to key
the IC-9700 himself (Ray's station: NB receives on a Pluto and tunes the
9700, which transmits into an upconverter). On 12/10/2026 Brian decided
that NB may key the 9700 by CAT PTT for its own digital-mode overs, as
WSJT-X does - never for voice. So the drivers learnt exactly two more
commands, PTT on and PTT off, and keep them behind a second gate: a
command that keys the radio is refused unless the caller holds a
`PttPermit` that is armed, on the thread that armed it. The permit is
made by the one owner of the digital over path (ohsnb/extrig.py CatPtt)
and armed by the engine's transmit thread for exactly one digital over,
so a stray `set_ptt(True)` - from a UI handler, a timer, a future feature
that thinks it would be convenient - is refused before a byte goes out,
as every other forbidden command is. Unkeying needs the permit too, but
not armed and from any thread (Halt, a lost link and app exit all unkey
from elsewhere), so that nothing but the over path's owner ever sends a
PTT command of either kind.

Menu writes, and why they are here at all. Until 12/10/2026 the package
could read the IC-9700's MOD Input menu and write nothing in it; Ray set
DATA MOD, USB MOD Level, satellite mode and the band on MAIN by hand.
Brian then asked for a setup assistant (ohsnb/rigsetup.py) that checks
those and, with the operator's one confirmation, sets them - and puts
them back as they were on request. So the CI-V driver learnt a short list
of write *shapes* (civ.py SETUP_WRITES), and each needs a `SetupPermit`
naming that exact body: the assistant arms one with precisely the writes
the operator has just confirmed, on its own thread, for the length of
the apply, so a stray menu write - another value, another item, another
thread, a moment later - is refused before a byte goes out, as PTT
without its permit is. Writes that change power, transmit or anything
the assistant does not set have no shape on the list and no permit can
name them.
"""
from __future__ import annotations

import socket
import threading
import time


class RigError(RuntimeError):
    """A rig problem with a sentence the operator can act on."""


class RigTimeout(RigError):
    """The rig did not answer in time (unplugged, wrong port, wrong baud,
    wrong CI-V address, or rigctld not running)."""


class ForbiddenCommand(RigError):
    """A command outside the driver's whitelist was about to be sent. This
    is a bug, never an operator error: the command is not sent."""


# Modes as the drivers report them, the same words for both links.
MODES = ("lsb", "usb", "am", "cw", "cw-r", "rtty", "rtty-r", "fm", "wfm", "dv", "dd", "other")
# Transmit audio sources (the IC-9700's MOD Input menu, in its own order).
MOD_INPUTS = ("mic", "acc", "mic,acc", "usb", "mic,usb", "lan")


class PttPermit:
    """What lets a driver send a PTT command (module docstring).
    `may_key()` is true only while armed, and only on the thread that armed
    it: the transmit thread of one digital over. Unkeying asks only that
    the caller holds the permit."""

    def __init__(self, owner: str = ""):
        self.owner = owner
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def arm(self) -> None:
        with self._lock:
            self._thread = threading.current_thread()

    def disarm(self) -> None:
        with self._lock:
            self._thread = None

    @property
    def armed(self) -> bool:
        return self._thread is not None

    def may_key(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread is threading.current_thread()


class SetupPermit:
    """What lets a driver send a setup write (module docstring): the exact
    bodies an operator confirmed, armed on the thread applying them.
    `allows(body)` is true only for one of those bodies, only while armed,
    and only on the arming thread."""

    def __init__(self, owner: str = ""):
        self.owner = owner
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._bodies: frozenset[bytes] = frozenset()

    def arm(self, bodies) -> None:
        with self._lock:
            self._bodies = frozenset(bytes(b) for b in bodies)
            self._thread = threading.current_thread()

    def disarm(self) -> None:
        with self._lock:
            self._thread = None
            self._bodies = frozenset()

    def allows(self, body: bytes) -> bool:
        with self._lock:
            return (self._thread is not None and self._thread is threading.current_thread()
                    and bytes(body) in self._bodies)


def check_ptt(on: bool, permit) -> None:
    """Raise ForbiddenCommand unless `permit` allows this PTT command."""
    if not isinstance(permit, PttPermit):
        raise ForbiddenCommand("A PTT command without the digital over's permit: not sent")
    if on and not permit.may_key():
        raise ForbiddenCommand("A PTT-on command outside an armed digital over: not sent")


class Rig:
    """One external radio. Every call is synchronous and may raise RigError;
    a caller polling from a thread (ohscore/rig/link.py) owns the timing."""

    name = "rig"

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def read_freq(self) -> int:
        """The operating frequency in Hz (the band the radio transmits on)."""
        raise NotImplementedError

    def set_freq(self, hz: int) -> None:
        raise NotImplementedError

    def set_ssb(self, mode: str) -> None:
        """Put the radio in "usb" or "lsb", its own filter for that mode.
        The only mode write there is: QO-100 NB uses it to take an IC-9700
        out of FM, which the narrowband transponder does not carry (Brian,
        08/10). Any other mode is a ValueError, not a command."""
        raise NotImplementedError

    def read_tx(self) -> bool:
        """True while the radio is transmitting."""
        raise NotImplementedError

    def set_data_mode(self, mode: str, data: bool) -> None:
        """Put the radio in "usb" or "lsb" with its DATA mode on (USB-D,
        LSB-D: the sound card feeds the modulator) or off. The one mode
        write besides set_ssb, added 12/10/2026 with CAT PTT: Brian asked
        that NB put the 9700 in the data variant for its digital modes, and
        back to plain SSB when NB goes back to SSB. Anything else is a
        ValueError, not a command."""
        raise NotImplementedError

    def set_ptt(self, on: bool, permit: PttPermit | None = None) -> None:
        """Key or unkey the radio under `permit` (module docstring);
        ForbiddenCommand without one. Does not read the state back: the
        caller confirms with read_tx()."""
        check_ptt(on, permit)
        raise ForbiddenCommand(f"{self.name} has no PTT command")

    def read_mod_input(self) -> dict | None:
        """Where the radio takes its transmit audio from, as far as the link
        can read it: {"data": the source with DATA mode on, "plain": with it
        off}, each one of MOD_INPUTS or "" (unknown). None where the link
        cannot read it at all (rigctld)."""
        return None

    def read_mode(self) -> tuple[str, bool]:
        """(mode, data): one of MODES, and whether the radio's DATA mode is
        on (its sound-card input feeds the modulator) where the link can
        tell; False where it cannot."""
        raise NotImplementedError

    def pushed(self) -> list[int]:
        """Frequencies the radio announced by itself since the last call
        (CI-V transceive), oldest first. Empty for links without it."""
        return []


class SocketPort:
    """A serial-port-shaped byte pipe over TCP, for `socket://host:port`
    port names (pyserial's own spelling, so the same text works in both):
    a CI-V emulator, a ser2net bridge, a remote shack. It exists so that
    CI-V runs without pyserial installed, which is what lets the test suite
    drive the real CI-V driver over a real socket against the emulator."""

    def __init__(self, url: str, timeout: float):
        hostport = url[len("socket://"):].strip("/")
        host, _, port = hostport.rpartition(":")
        if not host or not port.isdigit():
            raise RigError(f"{url!r} is not a socket://host:port address")
        try:
            self.sock = socket.create_connection((host, int(port)), timeout=2.0)
        except OSError as e:
            raise RigError(f"Could not connect to {host}:{port}: {e}") from e
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.timeout = timeout

    def write(self, data: bytes) -> int:
        try:
            self.sock.sendall(data)
        except OSError as e:
            raise RigError(f"The CI-V link failed: {e}") from e
        return len(data)

    def read(self, n: int) -> bytes:
        """Up to n bytes, waiting at most `timeout` for the first."""
        self.sock.settimeout(self.timeout)
        try:
            data = self.sock.recv(n)
        except socket.timeout:
            return b""
        except OSError as e:
            raise RigError(f"The CI-V link failed: {e}") from e
        if not data:
            raise RigError("The CI-V link was closed by the other end")
        return data

    def reset_input_buffer(self) -> None:
        self.sock.setblocking(False)
        try:
            while self.sock.recv(4096):
                pass
        except (BlockingIOError, OSError):
            pass
        finally:
            self.sock.setblocking(True)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def deadline(seconds: float) -> float:
    return time.monotonic() + seconds
