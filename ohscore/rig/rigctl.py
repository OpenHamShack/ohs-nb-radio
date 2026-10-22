r"""Hamlib's rigctld, over TCP: the rig shared with a logger or WSJT-X.

Written from Hamlib's rigctld(1) manual (the protocol section) - sources
and the command list in docs/ic9700-research.md. rigctld speaks the same
line protocol as rigctl: one command per line, answers one value per line,
and a bare "RPRT n" for set commands and for errors (0 is success,
negative is a Hamlib error code). Several programs can each hold a
connection to one rigctld, which serialises them onto the radio - the
reason to offer this link at all next to direct CI-V.

The commands sent, all of them (`ALLOWED`, checked before every send):

    f            get frequency            -> "<Hz>"
    F <Hz>       set frequency            -> "RPRT 0"
    t            get PTT                  -> "0" | "1" ...
    m            get mode                 -> "<MODE>" then "<passband Hz>"
    M USB|LSB 0  set mode, normal width   -> "RPRT 0"
    M PKTUSB|PKTLSB 0   the same with DATA on (since 12/10/2026: the
                 data variant NB puts the radio in for its digital modes)
    \chk_vfo     is VFO mode on?           -> "CHKVFO 0" | "CHKVFO 1"
    T 1 / T 0    set PTT on / off         -> "RPRT 0"   (only under a PttPermit)

Never L (set level, which includes RF power), never send_morse or
send_voice_mem, M only to USB or LSB (with or without DATA), and T only as the two lines above,
under the permit the digital over path holds - which is what the whitelist
enforces. T was never sent at all until 12/10/2026, when Brian decided
that NB may key the IC-9700 for its own digital overs as WSJT-X does
(ohscore/rig/base.py has the history and why a permit). `T 1` is Hamlib's
plain RIG_PTT_ON, which its Icom backend sends as 1C 00 01 - the same
command the CI-V driver sends - rather than 3 (ON_DATA), whose meaning
differs between backends. rigctld cannot read the MOD Input menu, so over
this link NB cannot check where the radio takes its transmit audio from.

rigctld started with --vfo (-o) wants a VFO argument on every one of
these commands. The driver asks `\chk_vfo` once on connecting ("CHKVFO 1"
when -o is on) and then adds `currVFO`, the VFO the radio has selected. `get_ptt` reports values above 1 for PTT from the data
or mic ports on some rigs (Hamlib's RIG_PTT_ON_MIC/ON_DATA); anything but
0 counts as transmitting.
"""
from __future__ import annotations

import re
import socket
import time

from .base import ForbiddenCommand, PttPermit, Rig, RigError, RigTimeout, check_ptt, deadline

DEFAULT_PORT = 4532

ALLOWED = (re.compile(r"f( currVFO)?"), re.compile(r"F (currVFO )?\d{1,11}"), re.compile(r"t( currVFO)?"),
           re.compile(r"m( currVFO)?"), re.compile(r"M (currVFO )?(USB|LSB|PKTUSB|PKTLSB) 0"), re.compile(r"\\chk_vfo"))

_MODES = {"USB": "usb", "LSB": "lsb", "CW": "cw", "CWR": "cw-r", "AM": "am", "FM": "fm", "WFM": "wfm",
          "RTTY": "rtty", "RTTYR": "rtty-r", "PKTUSB": "usb", "PKTLSB": "lsb", "PKTFM": "fm", "PKTAM": "am",
          "DSTAR": "dv"}
_DATA = {"PKTUSB", "PKTLSB", "PKTFM", "PKTAM"}


PTT_LINE = re.compile(r"T (currVFO )?([01])")


def allowed(line: str, permit: PttPermit | None = None) -> bool:
    """The whitelist (module docstring); the PTT lines only as `permit`
    allows them."""
    m = PTT_LINE.fullmatch(line)
    if m:
        try:
            check_ptt(m.group(2) == "1", permit)
        except ForbiddenCommand:
            return False
        return True
    return any(p.fullmatch(line) for p in ALLOWED)


class RigctldRig(Rig):
    name = "rigctld"

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 0.5):
        self.host, self.port, self.timeout = host or "127.0.0.1", int(port), float(timeout)
        self.sock: socket.socket | None = None
        self.buf = b""
        self.sent: list[str] = []          # every command line sent (tests read it)
        self.vfo = ""                      # "currVFO" when rigctld runs with --vfo

    def open(self) -> None:
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=2.0)
        except OSError as e:
            raise RigError(f"No rigctld at {self.host}:{self.port} ({e}). Start it with "
                           f"rigctld -m 3081 -r <port> (3081 is Hamlib's IC-9700)") from e
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""
        self.vfo = ""
        try:
            ans = self._ask("\\chk_vfo")[0]
        except RigError:
            ans = ""            # an older rigctld without it: the default protocol
        if ans.split()[-1:] == ["1"]:
            self.vfo = "currVFO"

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    # ------------------------------------------------------------ transport
    def _line(self, until: float) -> str:
        while b"\n" not in self.buf:
            left = until - time.monotonic()
            if left <= 0:
                raise RigTimeout(f"rigctld at {self.host}:{self.port} did not answer")
            self.sock.settimeout(left)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as e:
                raise RigError(f"The rigctld connection failed: {e}") from e
            if not chunk:
                raise RigError("rigctld closed the connection")
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode("ascii", "replace").strip()

    def _ask(self, cmd: str, lines: int = 1, permit: PttPermit | None = None) -> list[str]:
        if not allowed(cmd, permit):
            raise ForbiddenCommand(f"rigctld command {cmd!r} is not one this driver may send")
        if self.sock is None:
            raise RigError("rigctld is not connected")
        self.buf = b""
        self.sent.append(cmd)
        try:
            self.sock.sendall(cmd.encode("ascii") + b"\n")
        except OSError as e:
            raise RigError(f"The rigctld connection failed: {e}") from e
        until = deadline(self.timeout)
        out = [self._line(until)]
        if out[0].startswith("RPRT "):
            code = out[0][5:].strip()
            if code != "0":
                hint = (" (is rigctld running with --vfo? OpenHamShack needs it without)"
                        if code in ("-1", "-11") else "")
                raise RigError(f"rigctld refused {cmd.split()[0]!r}: error {code}{hint}")
            return out
        for _ in range(lines - 1):
            out.append(self._line(until))
        return out

    def _cmd(self, letter: str, *args: str) -> str:
        return " ".join([letter] + ([self.vfo] if self.vfo else []) + list(args))

    # ------------------------------------------------------------ the calls
    def read_freq(self) -> int:
        v = self._ask(self._cmd("f"))[0]
        try:
            return int(round(float(v)))
        except ValueError:
            raise RigError(f"rigctld answered {v!r} for the frequency") from None

    def set_freq(self, hz: int) -> None:
        r = self._ask(self._cmd("F", str(int(hz))))
        if r[0] != "RPRT 0":
            raise RigError(f"rigctld answered {r[0]!r} to a frequency change")

    def set_ssb(self, mode: str) -> None:
        if mode not in ("usb", "lsb"):
            raise ValueError(f"set_ssb takes usb or lsb, not {mode!r}")
        # Passband 0 is Hamlib's RIG_PASSBAND_NORMAL: the radio's usual
        # width for the mode. -1 (no change) would keep FM's 15 kHz.
        r = self._ask(self._cmd("M", mode.upper(), "0"))
        if r[0] != "RPRT 0":
            raise RigError(f"rigctld answered {r[0]!r} to a mode change")

    def set_data_mode(self, mode: str, data: bool) -> None:
        if mode not in ("usb", "lsb"):
            raise ValueError(f"set_data_mode takes usb or lsb, not {mode!r}")
        r = self._ask(self._cmd("M", ("PKT" if data else "") + mode.upper(), "0"))
        if r[0] != "RPRT 0":
            raise RigError(f"rigctld answered {r[0]!r} to a mode change")

    def read_tx(self) -> bool:
        v = self._ask(self._cmd("t"))[0]
        try:
            return int(v) != 0
        except ValueError:
            raise RigError(f"rigctld answered {v!r} for the transmit state") from None

    def set_ptt(self, on: bool, permit: PttPermit | None = None) -> None:
        check_ptt(on, permit)
        r = self._ask(self._cmd("T", "1" if on else "0"), permit=permit)
        if r[0] != "RPRT 0":
            raise RigError(f"rigctld answered {r[0]!r} to PTT {'on' if on else 'off'}")

    def read_mode(self) -> tuple[str, bool]:
        mode, _width = self._ask(self._cmd("m"), lines=2)
        return _MODES.get(mode.upper(), "other"), mode.upper() in _DATA
