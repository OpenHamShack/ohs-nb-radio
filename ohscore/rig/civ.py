"""Icom CI-V, written for the IC-9700 over its USB virtual COM port.

Written from Icom's "CI-V Reference Guide - IC-9700" and the IC-9700
instruction manual; every command, byte and default used here is listed
with its page in docs/ic9700-research.md, and what those documents leave
open is marked there [unverified]. It was written against
ohscore/rig/civsim.py, from the same pages - the two agree by construction,
so a misreading would be shared - and has since met a real IC-9700 on air
(Ray, 07/10/2026, Windows): reading and setting the frequency work. The
set-mode command (06) came after that and has not. The things most likely to differ on a real radio are named in
the research note; each has one place to change here.

Frames (CIV p.3):

    controller -> radio   FE FE <radio> <controller> <cmd> [<sub>] [data] FD
    radio -> controller   FE FE <controller> <radio> <cmd> [<sub>] [data] FD
    OK / NG               FE FE <controller> <radio> FB|FA FD

The radio's address defaults to A2 (manual, CI-V Address), the
controller's to E0. Frequencies are 5 bytes of BCD, least significant
pair first, the high nibble holding the more significant digit of each
pair (CIV p.4-5); 1268.123456 MHz is 56 34 12 68 12.

What this driver sends - all of it, and `allowed()` refuses anything else
before a byte goes out:

    03                read the operating frequency
    05 <5 BCD>        set the operating frequency          -> FB / FA
    04                read the operating mode and filter
    06 00 / 06 01     set the operating mode to LSB / USB  -> FB / FA
    1A 06             read DATA mode
    1A 06 01 <fil>    DATA mode on, keeping filter FIL1-3   -> FB / FA
    1A 06 00 00       DATA mode off (CIV p.17: filter 00 with it)
    1A 05 01 15       read DATA OFF MOD (where USB-mode audio comes from)
    1A 05 01 16       read DATA MOD (where USB-D audio comes from)
    1C 00             read the transmit state (no data byte: a READ)
    1C 00 01          PTT on  - only under an armed PttPermit (base.py)
    1C 00 00          PTT off - only with a PttPermit

For the setup assistant (ohsnb/rigsetup.py, 12/10/2026), reads - always
allowed, none of them changes anything:

    19 00             read the transceiver ID (CIV p.5): finds the address
    15 11 / 15 13     read the Po / ALC meter, 0000-0255 (CIV p.4 / p.5)
    16 5A             read satellite mode (CIV p.5)
    07 D2             read whether MAIN or SUB is selected (CIV p.4)
    25 00             read MAIN's selected VFO frequency (CIV p.11, p.23;
                      FA in satellite mode)
    1A 05 01 13       read USB MOD Level, 0000-0255 (CIV p.7)
    14 0A             read RF POWER, 0000-0255 = minimum to maximum (CIV
                      p.4; on 23 cm 0.1-10 W): the level set names it in
                      its advice. The read form only: with a value it is
                      the write, which nothing here can send

and writes, each refused unless a SetupPermit names that exact body
(base.py says why), and nothing outside these shapes even with one:

    1A 05 01 16 <00-05>      DATA MOD (CIV p.7)
    1A 05 01 13 <0000-0255>  USB MOD Level (CIV p.7)
    16 5A 00 / 01            satellite mode off / on (CIV p.5)
    07 B0                    exchange MAIN and SUB (CIV p.4)
    07 D0 / 07 D1            select MAIN / SUB (CIV p.4)

`1C 00 01` is `1C 00` with a data byte, and keys the transmitter (CIV
p.11): the reason for a whitelist rather than a list of dangers. Until
12/10/2026 nothing here could send it; since Brian decided that NB may key
the 9700 for its own digital overs, as WSJT-X does, these two bodies pass
the whitelist only with the permit the digital over path holds (base.py
says why a permit and not a plain entry). Nothing can send 17 (send CW),
28 (voice memory TX), 14 0A with a value (setting RF power), a menu write (1A 05 with a value)
or anything else that transmits or changes the radio (the setup writes
above aside, and only under their permit). The two MOD reads
are the menu read form, no value byte (CIV p.7: 0115 and 0116, 00 MIC,
01 ACC, 02 MIC+ACC, 03 USB, 04 MIC+USB, 05 LAN); with a value they would
be writes, which the whitelist refuses like any other.

The two DATA mode sets came with CAT PTT, on 12/10/2026, when Brian asked
that NB put the 9700 in USB-D (LSB-D through an inverting upconverter) for
its digital modes and back to plain SSB after. Of the two ways CIV p.17
and p.23 offer - `26 00 <mode> <data> <filter>`, or `06` and then `1A 06`
- this is the second: `06` is already here, and `26` with its filter
byte left out falls back to "DATA OFF and the default filter", which is
not what is wanted, while its behaviour with only the filter left out is
not documented. The filter written with DATA on is the one the radio
reports for the mode (04's second byte), so the operator's filter stays.

Decisions:

- **Echo and other traffic.** The radio's USB port does not echo by
  default ("CI-V USB Echo Back" OFF), but the REMOTE jack's single wire
  always does, and either can carry the radio's transceive broadcasts
  (command 00, addressed to 00) or a second controller's traffic. So the
  reader takes whole frames and keeps only those addressed to us from our
  radio; our own echo, broadcasts and anyone else's frames are skipped
  (broadcast frequencies are kept for `pushed()`). A frame broken by a
  collision (FC bytes, the single-wire bus's jammer code) is dropped.
- **One retry.** A read that times out is sent once more before the call
  fails: a single frame lost on a busy bus should cost one poll, not a
  "link lost". A set is never retried blind - the frequency is read back
  on the next poll anyway.
- **Port names.** Anything pyserial opens (COM5, /dev/ttyUSB0), plus
  socket://host:port, handled here without pyserial so the emulator and
  a ser2net bridge work on a machine without it.
"""
from __future__ import annotations

import time

from .base import (MOD_INPUTS, ForbiddenCommand, PttPermit, Rig, RigError, RigTimeout, SetupPermit, SocketPort,
                   check_ptt, deadline)

PRE = b"\xfe\xfe"
EOM = 0xFD
OK, NG, JAM = 0xFB, 0xFA, 0xFC
CONTROLLER = 0xE0
IC9700 = 0xA2
BROADCAST = 0x00

C_FREQ_PUSH = 0x00      # transceive: frequency announced by the radio
C_MODE_PUSH = 0x01      # transceive: mode announced by the radio
C_READ_FREQ = 0x03
C_READ_MODE = 0x04
C_SET_FREQ = 0x05
C_SET_MODE = 0x06
C_EXT = 0x1A            # 1A 06: DATA mode
C_TX = 0x1C             # 1C 00: transmit state

MODES = {0x00: "lsb", 0x01: "usb", 0x02: "am", 0x03: "cw", 0x04: "rtty", 0x05: "fm", 0x06: "wfm",
         0x07: "cw-r", 0x08: "rtty-r", 0x17: "dv", 0x22: "dd"}

READ_FREQ = bytes([C_READ_FREQ])
READ_MODE = bytes([C_READ_MODE])
READ_DATA = bytes([C_EXT, 0x06])
READ_TX = bytes([C_TX, 0x00])
PTT_ON = bytes([C_TX, 0x00, 0x01])
PTT_OFF = bytes([C_TX, 0x00, 0x00])
READ_MOD_PLAIN = bytes([C_EXT, 0x05, 0x01, 0x15])     # DATA OFF MOD
READ_MOD_DATA = bytes([C_EXT, 0x05, 0x01, 0x16])      # DATA MOD
DATA_OFF = bytes([C_EXT, 0x06, 0x00, 0x00])

# The setup assistant's reads (module docstring).
C_VFO = 0x07
C_METER = 0x15
C_FUNC = 0x16
C_ID = 0x19
C_LEVEL = 0x14
C_VFO_FREQ = 0x25
READ_ID = bytes([C_ID, 0x00])
READ_PO = bytes([C_METER, 0x11])
READ_ALC = bytes([C_METER, 0x13])
READ_SAT = bytes([C_FUNC, 0x5A])
READ_SELECTED = bytes([C_VFO, 0xD2])
READ_MAIN_FREQ = bytes([C_VFO_FREQ, 0x00])
READ_USB_MOD = bytes([C_EXT, 0x05, 0x01, 0x13])
READ_RF_POWER = bytes([C_LEVEL, 0x0A])
# ...and its writes, each only under a SetupPermit naming it.
EXCHANGE_BANDS = bytes([C_VFO, 0xB0])
SELECT_MAIN = bytes([C_VFO, 0xD0])
SELECT_SUB = bytes([C_VFO, 0xD1])
METERS = {"po": READ_PO, "alc": READ_ALC}


def level_bcd(v: int) -> bytes:
    """A 0-255 level as the 9700 writes it: four BCD digits in two bytes,
    most significant first (CIV p.4-7, "0000 ~ 0255"; 0128 is 01 28)."""
    v = int(v)
    if not 0 <= v <= 255:
        raise ValueError(f"{v} is not a 0-255 level")
    return bytes([(v // 1000) << 4 | (v // 100) % 10, ((v // 10) % 10) << 4 | v % 10])


def from_level(data: bytes) -> int:
    if len(data) < 2:
        raise ValueError(f"short level {data.hex(' ')}")
    digits = [data[0] >> 4, data[0] & 0x0F, data[1] >> 4, data[1] & 0x0F]
    if any(d > 9 for d in digits):
        raise ValueError(f"{data[:2].hex(' ')} is not BCD")
    return digits[0] * 1000 + digits[1] * 100 + digits[2] * 10 + digits[3]


def set_data_mod(src: str) -> bytes:
    """The write that sets DATA MOD to `src`, one of base.MOD_INPUTS."""
    return READ_MOD_DATA + bytes([MOD_INPUTS.index(src)])


def set_usb_mod_level(v: int) -> bytes:
    return READ_USB_MOD + level_bcd(v)


def set_satellite(on: bool) -> bytes:
    return READ_SAT + bytes([0x01 if on else 0x00])


def setup_write_shape(body: bytes) -> bool:
    """Whether `body` is one of the setup writes at all (module docstring);
    a permit naming it is still needed to send it."""
    if body in (EXCHANGE_BANDS, SELECT_MAIN, SELECT_SUB, set_satellite(False), set_satellite(True)):
        return True
    if len(body) == 5 and body[:4] == READ_MOD_DATA:
        return body[4] < len(MOD_INPUTS)
    if len(body) == 6 and body[:4] == READ_USB_MOD:
        try:
            return from_level(body[4:]) <= 255
        except ValueError:
            return False
    return False


def data_on(fil: int) -> bytes:
    return bytes([C_EXT, 0x06, 0x01, fil if fil in (1, 2, 3) else 1])
# 06 with the mode byte alone: no filter byte, so the radio keeps the
# filter it already has for that mode (the operator's choice, made on the
# radio) instead of NB imposing FIL1-3. [unverified] on a real 9700 - the research
# note says what to send if it answers FA. Only these two: FM, AM, DV and the
# rest are never written.
SET_SSB = {"lsb": bytes([C_SET_MODE, 0x00]), "usb": bytes([C_SET_MODE, 0x01])}


def to_bcd(hz: int, nbytes: int = 5) -> bytes:
    """Hz as Icom BCD: least significant digit pair first."""
    hz = int(hz)
    if hz < 0 or hz >= 10 ** (2 * nbytes):
        raise ValueError(f"{hz} Hz does not fit {nbytes} BCD bytes")
    out = bytearray()
    for _ in range(nbytes):
        lo = hz % 10
        hz //= 10
        hi = hz % 10
        hz //= 10
        out.append((hi << 4) | lo)
    return bytes(out)


def from_bcd(data: bytes) -> int:
    hz, mul = 0, 1
    for b in data:
        hi, lo = b >> 4, b & 0x0F
        if hi > 9 or lo > 9:
            raise ValueError(f"{data.hex(' ')} is not BCD")
        hz += lo * mul + hi * mul * 10
        mul *= 100
    return hz


def frame(to: int, frm: int, body: bytes) -> bytes:
    return PRE + bytes([to, frm]) + body + bytes([EOM])


def allowed(body: bytes, permit: PttPermit | None = None, setup: SetupPermit | None = None) -> bool:
    """The whitelist: exactly the commands listed in the module docstring,
    the two PTT commands only as `permit` allows them, each setup write
    only when `setup` names it."""
    if body in (READ_FREQ, READ_MODE, READ_DATA, READ_TX, READ_MOD_PLAIN, READ_MOD_DATA, DATA_OFF,
                data_on(1), data_on(2), data_on(3)) or body in SET_SSB.values():
        return True
    if body in (READ_ID, READ_PO, READ_ALC, READ_SAT, READ_SELECTED, READ_MAIN_FREQ, READ_USB_MOD, READ_RF_POWER):
        return True
    if setup_write_shape(body):
        return isinstance(setup, SetupPermit) and setup.allows(body)
    if body in (PTT_ON, PTT_OFF):
        try:
            check_ptt(body == PTT_ON, permit)
        except ForbiddenCommand:
            return False
        return True
    return len(body) == 6 and body[0] == C_SET_FREQ


class FrameReader:
    """Bytes in, whole frames out as (to, from, body). Anything before a
    preamble is skipped; a frame containing a jammer byte (FC) is a
    collision and dropped whole."""

    def __init__(self):
        self.buf = bytearray()
        self.jammed = 0              # frames dropped as collisions (the diagnostic reports it)

    def feed(self, data: bytes) -> list[tuple[int, int, bytes]]:
        self.buf += data
        out = []
        while True:
            i = self.buf.find(PRE)
            if i < 0:
                # Keep a lone trailing FE: it may be the first half of a preamble.
                self.buf = self.buf[-1:] if self.buf[-1:] == b"\xfe" else bytearray()
                return out
            if i:
                del self.buf[:i]
            j = self.buf.find(bytes([EOM]), 2)
            if j < 0:
                return out
            raw = bytes(self.buf[:j + 1])
            del self.buf[:j + 1]
            inner = raw[2:-1]
            # Extra FE bytes (a repeated preamble) before the addresses.
            while inner[:1] == b"\xfe":
                inner = inner[1:]
            if JAM in inner or len(inner) < 3:
                self.jammed += JAM in inner
                continue
            out.append((inner[0], inner[1], inner[2:]))


def open_port(port: str, baud: int, timeout: float):
    """A byte pipe for `port`: socket://host:port here, anything else
    through pyserial (imported only now, so a machine without it can still
    use rigctld or the emulator)."""
    if not port:
        raise RigError("No CI-V port set (Settings > Transmitter): the IC-9700's USB port, e.g. COM5 or "
                       "/dev/ttyUSB0")
    if port.startswith("socket://"):
        return SocketPort(port, timeout)
    try:
        import serial
    except ImportError:
        from .. import host
        raise RigError(host.hint("pyserial")) from None
    try:
        return serial.serial_for_url(port, baudrate=int(baud), timeout=timeout, write_timeout=1.0)
    except (serial.SerialException, ValueError, OSError) as e:
        raise RigError(f"Could not open {port}: {e}. Is the IC-9700 switched on and connected by USB, "
                       "and is no other program using that port?") from e


class CivRig(Rig):
    name = "civ"

    def __init__(self, port: str, baud: int = 115200, address: int = IC9700, controller: int = CONTROLLER,
                 timeout: float = 0.25, transport=None):
        self.port_name, self.baud = port, int(baud)
        self.addr, self.me = int(address), int(controller)
        self.timeout = float(timeout)
        self.port = transport
        self.reader = FrameReader()
        self.pushed_freqs: list[int] = []
        self.sent: list[bytes] = []          # every body sent (tests read it)
        self.echoes = 0                      # our own frames heard back (CI-V USB Echo Back, the REMOTE jack)
        self.strays = 0                      # frames for or from anyone else (the diagnostic reports both)

    def open(self) -> None:
        if self.port is None:
            self.port = open_port(self.port_name, self.baud, min(0.05, self.timeout))
        try:
            self.port.reset_input_buffer()
        except Exception:  # noqa: BLE001 - not every pipe has one
            pass

    def close(self) -> None:
        if self.port is not None:
            try:
                self.port.close()
            except Exception:  # noqa: BLE001
                pass
            self.port = None

    # ------------------------------------------------------------ transport
    def _send(self, body: bytes, permit: PttPermit | None = None, setup: SetupPermit | None = None) -> None:
        if not allowed(body, permit, setup):
            raise ForbiddenCommand(f"CI-V command {body.hex(' ')} is not one this driver may send")
        if self.port is None:
            raise RigError("The CI-V port is not open")
        self.sent.append(bytes(body))
        try:
            self.port.write(frame(self.addr, self.me, body))
        except RigError:
            raise
        except Exception as e:  # noqa: BLE001 - pyserial's SerialException and friends
            raise RigError(f"Writing to {self.port_name} failed: {e}") from e

    def _frames(self, until: float):
        while time.monotonic() < until:
            try:
                data = self.port.read(64)
            except RigError:
                raise
            except Exception as e:  # noqa: BLE001
                raise RigError(f"Reading {self.port_name} failed: {e}") from e
            for to, frm, body in self.reader.feed(data or b""):
                if frm == self.addr and to == BROADCAST and body[:1] == bytes([C_FREQ_PUSH]) and len(body) >= 6:
                    try:
                        self.pushed_freqs.append(from_bcd(body[1:6]))
                    except ValueError:
                        pass
                    continue
                if to == self.me and frm == self.addr:
                    yield body
                # Anything else: our own echo, another controller, a mode broadcast.
                elif to == self.addr and frm == self.me:
                    self.echoes += 1
                else:
                    self.strays += 1

    def _transact(self, body: bytes, reply_prefix: bytes | None, tries: int = 2,
                  permit: PttPermit | None = None, setup: SetupPermit | None = None) -> bytes:
        """Send `body`; return the radio's reply body that starts with
        `reply_prefix` (a read), or b"" for FB (a set). FA raises."""
        for attempt in range(tries):
            self._send(body, permit, setup)
            for got in self._frames(deadline(self.timeout)):
                if got[:1] == bytes([NG]):
                    raise RigError(f"the radio answered NG (FA) to {body.hex(' ')}")
                if reply_prefix is None and got[:1] == bytes([OK]):
                    return b""
                if reply_prefix is not None and got.startswith(reply_prefix):
                    return got
        raise RigTimeout(f"No answer on {self.port_name} from CI-V address {self.addr:02X}h. Check the port, "
                         f"the baud rate and the radio's CI-V Address (IC-9700 default A2h)")

    # ------------------------------------------------------------ the calls
    def read_freq(self) -> int:
        r = self._transact(READ_FREQ, READ_FREQ)
        if len(r) < 6:
            raise RigError(f"Short frequency reply {r.hex(' ')}")
        try:
            return from_bcd(r[1:6])
        except ValueError as e:
            raise RigError(str(e)) from None

    def set_freq(self, hz: int) -> None:
        self._transact(bytes([C_SET_FREQ]) + to_bcd(hz), None, tries=1)

    def set_ssb(self, mode: str) -> None:
        if mode not in SET_SSB:
            raise ValueError(f"set_ssb takes usb or lsb, not {mode!r}")
        self._transact(SET_SSB[mode], None, tries=1)

    def read_tx(self) -> bool:
        r = self._transact(READ_TX, READ_TX)
        if len(r) < 3:
            raise RigError(f"Short transmit-state reply {r.hex(' ')}")
        return r[2] != 0

    def set_data_mode(self, mode: str, data: bool) -> None:
        if mode not in SET_SSB:
            raise ValueError(f"set_data_mode takes usb or lsb, not {mode!r}")
        r = self._transact(READ_MODE, READ_MODE)
        if len(r) < 2 or MODES.get(r[1]) != mode:
            self._transact(SET_SSB[mode], None, tries=1)
            r = self._transact(READ_MODE, READ_MODE)
        fil = r[2] if len(r) >= 3 else 1
        self._transact(data_on(fil) if data else DATA_OFF, None, tries=1)

    def set_ptt(self, on: bool, permit: PttPermit | None = None) -> None:
        # Refused here, before the port is looked at, as well as in _send:
        # the sentence then names PTT rather than a byte string.
        check_ptt(on, permit)
        # Never retried blind, like a frequency set: the caller reads the
        # transmit state back (1C 00) and acts on what the radio says.
        self._transact(PTT_ON if on else PTT_OFF, None, tries=1, permit=permit)

    def read_mod_input(self) -> dict | None:
        out = {}
        for key, body in (("plain", READ_MOD_PLAIN), ("data", READ_MOD_DATA)):
            try:
                r = self._transact(body, body)
                v = r[len(body)] if len(r) > len(body) else None
            except RigTimeout:
                raise
            except RigError:
                v = None              # FA: a firmware without the item
            # BCD and binary agree for 00-05.
            out[key] = MOD_INPUTS[v] if v is not None and v < len(MOD_INPUTS) else ""
        return out

    def read_mode(self) -> tuple[str, bool]:
        r = self._transact(READ_MODE, READ_MODE)
        mode = MODES.get(r[1], "other") if len(r) >= 2 else "other"
        try:
            d = self._transact(READ_DATA, READ_DATA)
            data = len(d) >= 3 and d[2] != 0
        except RigError:
            data = False
        return mode, data

    def pushed(self) -> list[int]:
        out, self.pushed_freqs = self.pushed_freqs, []
        return out

    # ------------------------------------------------- the setup assistant's
    # (module docstring; ohsnb/rigsetup.py): reads, and one write call that
    # needs the assistant's SetupPermit naming the exact body.
    def _read_byte(self, body: bytes, what: str) -> int:
        r = self._transact(body, body)
        if len(r) <= len(body):
            raise RigError(f"Short {what} reply {r.hex(' ')}")
        return r[len(body)]

    def _read_level(self, body: bytes, what: str) -> int:
        r = self._transact(body, body)
        try:
            return from_level(r[len(body):])
        except ValueError as e:
            raise RigError(f"Bad {what} reply {r.hex(' ')}: {e}") from None

    def read_id(self) -> int:
        """The transceiver ID (19 00). CIV p.5 lists the command but not its
        reply; read as `19 00 <id>`, the radio's own address on Icoms
        [unverified on a real 9700]. A reply without the byte still proves
        the address, which is what the assistant wants: then the address."""
        r = self._transact(READ_ID, READ_ID)
        return r[2] if len(r) > 2 else self.addr

    def read_meter(self, which: str) -> int:
        """"po" or "alc": 0-255 as the radio reports it (CIV p.4: Po 0143 =
        50 %, 0213 = 100 %; p.5: ALC 0000 minimum to 0120 maximum)."""
        return self._read_level(METERS[which], f"{which} meter")

    def read_satellite(self) -> bool:
        return self._read_byte(READ_SAT, "satellite mode") != 0

    def read_selected(self) -> str:
        """"main" or "sub": the band 03 and 05 act on (07 D2, CIV p.4; read
        as `07 D2 <00|01>` [unverified reply])."""
        return "sub" if self._read_byte(READ_SELECTED, "band selection") else "main"

    def read_main_freq(self) -> int:
        """MAIN's frequency whichever band is selected (25 00: "Only MAIN
        band", CIV p.11, p.23). FA - a RigError - in satellite mode."""
        r = self._transact(READ_MAIN_FREQ, READ_MAIN_FREQ)
        if len(r) < 7:
            raise RigError(f"Short MAIN frequency reply {r.hex(' ')}")
        try:
            return from_bcd(r[2:7])
        except ValueError as e:
            raise RigError(str(e)) from None

    def read_usb_mod_level(self) -> int:
        return self._read_level(READ_USB_MOD, "USB MOD Level")

    def read_rf_power(self) -> int:
        """RF POWER, 0-255 (14 0A, CIV p.4: 0000 minimum to 0255 maximum)."""
        return self._read_level(READ_RF_POWER, "RF power")

    def setup_write(self, body: bytes, setup: SetupPermit) -> None:
        """Send one setup write: ForbiddenCommand, before anything is sent,
        unless `setup` names this body. FB, or a RigError; never retried
        blind - the assistant reads every value back."""
        if not (setup_write_shape(body) and isinstance(setup, SetupPermit) and setup.allows(body)):
            raise ForbiddenCommand(f"CI-V setup write {body.hex(' ')} without the assistant's confirmation: "
                                   "not sent")
        self._transact(body, None, tries=1, setup=setup)


def find_address(port: str, baud: int = 115200, transport=None, cancel=None, sweep_timeout: float = 0.05,
                 first: tuple = (IC9700,), sweep: bool = True) -> tuple[int, int] | None:
    """Find the radio's CI-V address on `port` by asking for its ID (19 00):
    the IC-9700's default A2 first, with the usual timeout and retry, then
    every other address an Icom may be given (01-DF, the range CIV p.7
    gives item 0128; not 00, the broadcast, nor E0, ours), briefly each:
    over USB the answer takes milliseconds, so the whole sweep costs about
    ten seconds. Reads only. (address, id), or None when nothing answered
    or `cancel()` came true. Raises RigError when the port will not open.
    `sweep` False asks only the `first` addresses."""
    rig = CivRig(port, baud, first[0], transport=transport)
    rig.open()
    try:
        order = list(first) + ([a for a in range(0x01, 0xE0) if a not in first] if sweep else [])
        for i, addr in enumerate(order):
            if cancel is not None and cancel():
                return None
            if i == len(first):
                rig.timeout = sweep_timeout
                # The pipe's own read wait too (pyserial's and SocketPort's
                # are both `timeout`), or each address costs that instead.
                try:
                    rig.port.timeout = min(sweep_timeout, rig.port.timeout)
                except (AttributeError, TypeError, ValueError):
                    pass
            rig.addr = addr
            try:
                r = rig._transact(READ_ID, READ_ID, tries=2 if i < len(first) else 1)
            except RigTimeout:
                continue
            except RigError:
                return addr, addr            # an NG still came from that address
            return addr, (r[2] if len(r) > 2 else addr)
        return None
    finally:
        rig.close()


# The rates the 9700's CI-V USB Baud Rate menu offers, the ones radios are
# most often left at first. Ray's 9700 answered only at 19200 (12/10/2026),
# while NB asked at 115200 alone.
BAUDS = (19200, 115200, 9600, 38400, 57600, 4800)


def find_radio(port: str, baud: int = 115200, address: int = IC9700, cancel=None) -> tuple[int, int, int] | None:
    """Find the radio on `port`: (address, id, baud), or None. Asks at
    `address` (and A2) at `baud` first, then at every other rate in BAUDS,
    then sweeps every address at `baud` (find_address). Reads only.
    Raises RigError when the port will not open."""
    first = tuple(dict.fromkeys((address, IC9700)))
    for b in dict.fromkeys((int(baud),) + BAUDS):
        if cancel is not None and cancel():
            return None
        hit = find_address(port, b, cancel=cancel, first=first, sweep=False)
        if hit:
            return hit[0], hit[1], b
    hit = find_address(port, int(baud), cancel=cancel, first=first)
    return (hit[0], hit[1], int(baud)) if hit else None
