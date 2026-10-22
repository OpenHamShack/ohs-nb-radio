"""Hermes-Lite 2: openHPSDR Protocol 1 over UDP, standard library + numpy.

Written from docs/ham/hl2-research.md (the protocol facts, with their
sources) and docs/ham/DESIGN-HAM.md section 4.2 (what the driver must do);
no client code was copied. NOT YET TESTED ON HARDWARE: there is no HL2 on
any development host. Everything here has run only against our own
emulator (ohscore/devices/hl2sim.py), which was written from the same
documents - so the two agree by construction, and a misreading of the
documents would be shared by both. The items most likely to be wrong are
listed under "Unverified" below; each has a single place to change.

Decisions:

- **Pacing without a timer.** The HL2 must receive EP2 datagrams (C&C
  registers and TX IQ, always 48 kS/s) at ~381/s, or its TX FIFO underflows
  and, when they stop altogether, its watchdog stops streaming. The rate is
  taken from the radio itself: one EP2 is sent per N EP6 datagrams, N =
  rate / 48 000, counted by the EP6 *sequence numbers*, so a datagram lost
  on the network still counts and the radio's crystal, not the host's
  clock, decides the pace. A long gap is not repaid in a burst (that would
  only overflow the radio's FIFO); at most CATCH_UP datagrams are sent at
  once and the rest of the debt is forgiven.
- **One socket thread** receives EP6 with recvfrom_into straight into a
  preallocated batch buffer, sends EP2 as the sequence numbers say, and
  every ~10 ms of samples unpacks the whole batch at once with numpy (one
  vectorised 24-bit sign extension). The per-datagram Python work is a
  header check and a sequence-number subtraction - unavoidable, since each
  datagram is its own system call.
- **Lost datagrams are zero-filled** at their place in the stream, so the
  sample count stays true to elapsed time (FT8's slot timing depends on it)
  and are counted in `overruns`. Duplicates and late (reordered) datagrams
  are dropped and counted; a forward jump of more than two seconds is taken
  as a restarted radio and re-anchors without filling.
- **MOX** is C0 bit 0 of every frame while keyed and clear otherwise; EP2
  keeps flowing with zero IQ and MOX clear while unkeyed (the gateware's
  watchdog needs it). The HL2 itself drops TX ~12 ms (PTT hang) after TX
  samples stop arriving, so any death of this process unkeys within
  milliseconds even if nothing here runs; close() and the thread's failure
  path clear MOX explicitly as well. The watchdog is **never disabled**:
  the start command never sets bit 7, and register 0x39 is written once at
  open with the *enable* code, in case an earlier RX-only client disabled
  it (the HL2 keeps that until power-off).
- **Drive** is continuous 0..1 in amplitude. The top 7.5 dB use the drive
  register's 16 steps (0x09 bits 31:28, 0.5 dB each); the step chosen is
  the lowest at or above the request, and IQ amplitude scaling makes up the
  remainder, so step x scale is exactly the request. Below -7.5 dB the
  register sits at step 0 and the IQ alone scales. Scaling is applied when
  each EP2 is built, not when write() is called, so set_drive(0) silences
  samples already queued - up to TX_HIGH_WATER (40 ms), since write()
  returns with that much left - and the radio's own TX buffer
  (tx_latency_ms, 20 ms) then plays out at the lowest drive step. A caller
  that wants an over's end on air at full drive calls tx_finish() and waits
  for tx_queued() to reach zero before set_drive(0) / tx_stop(): see
  tx_queued() for why that includes the radio's buffer.
- **TX rate.** The engine writes IQ at `fs` (the receive rate); the HL2
  takes 48 kS/s. fs / 48 000 is an integer at every supported rate, so
  write() decimates with ohscore.dsp.multirate (flat to +-20.2 kHz,
  stopband from +-27.8 kHz). The signal must therefore sit within
  +-20 kHz of the TX frequency (set_tx_freq); anything further out is
  filtered away, not transmitted.
- **Filters (N2ADR board).** The OC bits (register 0x00 bits 23:17) follow
  Quisk's default band map from the research, chosen by frequency with
  boundaries half-way between the bands' groups: the receive frequency
  while unkeyed and the TX frequency while keyed. The board's RX-only
  3 MHz high-pass (bit 6) is in from 80 m up, as the map has it.
- **Duplex** (register 0x00 bit 2) is always set, so RX1 stays on its own
  frequency while keyed (the engine keeps the scope running during TX) and
  the TX NCO is set independently.
- **Minimum gateware 72.8** (MIN_GATEWARE): the research dates the 12 ms
  PTT hang and the 20 ms TX buffer default - the behaviour that ends TX
  by itself when the host goes quiet - to gateware 72p8; older gateware is
  documented to stay in TX. The PTT hang and buffer latency (register
  0x17) are also written explicitly, so the radio cannot be left with a
  hang of 31 ("until MOX drops") by another client.

Unverified (to settle on the first hardware session, in this order):

- **TX I/Q order.** The USB protocol document says TX I and Q are swapped
  relative to RX ("a historical bug"); whether HL2 clients swap is not
  known. This sends I in the slot labelled I. cfg `hl2TxSwapIQ` swaps them.
  A wrong choice mirrors the transmitted spectrum about the TX frequency
  (USB becomes LSB): the first key-up must be a known tone offset into a
  dummy load, watched on a receiver.
- **Forward/reverse power** has no formula; Quisk uses a calibration
  spline. Until Brian's HL2 is measured against a power meter, power_w()
  is a PROVISIONAL square law (watts proportional to raw squared) through
  two of Quisk's published points, 3382 -> 4.98 W and 4093 -> 7.29 W (the
  law fits both to 0.1 %). It is certainly wrong at low power, where the
  detector's diode offset dominates; telemetry() marks it "calibrated":
  False. The same curve is assumed for reverse power.
- **PA current** uses Quisk's formula with its 1000/1270 input divider;
  hermeslite.py omits the divider. Quisk shows the value, so it is used.
- **TX inhibit** (response address 0, bit 25) is documented as active low;
  it is read as "inhibited when the bit is 0". If that is backwards a
  normal radio reports itself inhibited on the first key-up - loud, and
  safe, since the gateware enforces the inhibit itself either way.
- **FIFO flags**: bits 15:14 of response address 0 read as 10 = underflow,
  11 = overflow (bit 15 = "something happened", bit 14 = which).
- **Drive steps** are assumed linear in dB (0.5 dB each).
- **OC bits above 30 MHz** (receive only, the HL2 tunes to 38.4 MHz): the
  10 m low-pass (0x60) is left in; whether no bits at all bypasses the
  board is not documented.
- The real **watchdog timeout** is undocumented ("about 4 s" appears only
  on an AI-generated page); this driver sends EP2 continuously, so it only
  matters when the host stops.
"""
from __future__ import annotations

import collections
import math
import socket
import struct
import threading
import time

import numpy as np

from .base import Device, DeviceError

PORT = 1024                 # discovery and streaming
ALT_PORT = 1025             # the HL2 also answers here (hermeslite.py uses it alongside SDR software)
BOARD_HL2 = 0x06
BOARD_NAMES = {0x00: "Metis", 0x01: "Hermes (or an HL2 in Hermes emulation)", 0x02: "Griffin",
               0x04: "Angelia", 0x05: "Orion", 0x06: "Hermes-Lite 2", 0x0A: "Orion Mk II"}
MIN_GATEWARE = (72, 8)      # module docstring: the first that ends TX by itself

RATE_CODES = {48_000: 0, 96_000: 1, 192_000: 2, 384_000: 3}     # register 0x00 bits 25:24
TX_FS = 48_000.0
DGRAM = 1032                # EF FE 01 ep seq32, then two 512-byte frames
PER_FRAME = 63              # samples per frame, one receiver (504 / (6*1 + 2))
PER_DGRAM = 2 * PER_FRAME
FULL_SCALE_RX = float(1 << 23)
FULL_SCALE_TX = 32767.0

DRIVE_STEPS = 16
DRIVE_SPAN_DB = 7.5         # the AD9866's whole TX gain range; the rest is IQ scaling
FULL_W = 5.0                # "about 5 W on all HF amateur bands" (HL2 FAQ)
RF1_W = 0.05                # PA off: the low-level output, <= 17 dBm

LNA_MIN, LNA_MAX = -12, 48
PTT_HANG_MS = 12            # gateware default; 31 would mean "until MOX drops" and is never sent
TX_LATENCY_MS = 20          # gateware default TX buffer latency

CATCH_UP = 4                # most EP2 datagrams sent at once after a gap (module docstring)
TX_HIGH_WATER = 0.04        # s of 48 kHz IQ left queued when write() returns (see drain())
RX_KEEP = 2.0               # s of receive samples held for a slow reader before the oldest go
MAX_GAP_S = 2.0             # a sequence jump longer than this re-anchors instead of zero-filling

# Register addresses (C0 bits 6:1).
R_CONFIG, R_TX_FREQ, R_RX1_FREQ, R_DRIVE, R_LNA, R_TXBUF, R_WATCHDOG = 0x00, 0x01, 0x02, 0x09, 0x0A, 0x17, 0x39
ROTATION = (R_CONFIG, R_TX_FREQ, R_RX1_FREQ, R_DRIVE, R_LNA, R_TXBUF)
WATCHDOG_ENABLE = 0x8 << 24  # register 0x39 bits 27:24: 0x8 enable (0x9 would disable - never sent)

# N2ADR filter board: Quisk's default band map (research section 5), by
# frequency. Boundaries sit between the bands each filter serves.
OC_MAP = ((2.75e6, 0x01),    # 160 m LPF; no HPF, so AM broadcast passes on receive
          (4.6e6, 0x42),     # 80 m LPF + 3 MHz HPF
          (8.7e6, 0x44),     # 60/40 m
          (16.2e6, 0x48),    # 30/20 m
          (23.2e6, 0x50),    # 17/15 m
          (math.inf, 0x60))  # 12/10 m (and, unverified, above 30 MHz on receive)


# --------------------------------------------------------------------------
# Encodings and conversions (pure; the tests check them against the research)
# --------------------------------------------------------------------------
def oc_bits(hz: float) -> int:
    """N2ADR filter-board OC bits (OC0-6) for a frequency."""
    for top, bits in OC_MAP:
        if hz < top:
            return bits
    return OC_MAP[-1][1]


def config_word(rate: int, oc: int, receivers: int = 1, duplex: bool = True) -> int:
    """Register 0x00: rate bits 25:24, OC bits 23:17, receivers-1 in 6:3,
    duplex bit 2. Bit 11 (band volts, which bypasses the thermal cut-out)
    and bit 7 of anything are never set."""
    return (RATE_CODES[int(rate)] << 24) | ((oc & 0x7F) << 17) | (((receivers - 1) & 0xF) << 3) | \
        (0x4 if duplex else 0)


def lna_byte(db: float) -> int:
    """Register 0x0A bits 7:0: bit 6 = direct gain, bits 5:0 = dB + 12 (-12..+48 dB)."""
    g = int(round(max(LNA_MIN, min(LNA_MAX, float(db)))))
    return ((g + 12) & 0x3F) | 0x40


def drive_split(x: float) -> tuple[int, float]:
    """Drive 0..1 (amplitude) -> (register step 0..15, IQ scale 0..1),
    with step_gain(step) * scale == x (module docstring)."""
    x = max(0.0, min(1.0, float(x)))
    if x <= 0.0:
        return 0, 0.0
    want = (20 * math.log10(x) + DRIVE_SPAN_DB) / (DRIVE_SPAN_DB / (DRIVE_STEPS - 1))
    step = max(0, min(DRIVE_STEPS - 1, math.ceil(want - 1e-9)))
    return step, min(1.0, x / step_gain(step))


def step_gain(step: int) -> float:
    """Amplitude of drive-register step 0..15 relative to full (0.5 dB steps)."""
    return 10 ** ((-DRIVE_SPAN_DB + step * DRIVE_SPAN_DB / (DRIVE_STEPS - 1)) / 20)


def drive_word(step: int, pa: bool = True) -> int:
    """Register 0x09: drive in bits 31:28 (only those are used), PA enable bit 19."""
    return ((step & 0xF) << 28) | (1 << 19 if pa else 0)


def txbuf_word(latency_ms: int = TX_LATENCY_MS, hang_ms: int = PTT_HANG_MS) -> int:
    """Register 0x17: PTT hang in bits 12:8 (never 31), TX buffer latency in 6:0."""
    hang = max(0, min(30, int(hang_ms)))
    lat = max(1, min(70, int(latency_ms)))
    return (hang << 8) | lat


def temp_c(raw: int) -> float:
    """Temperature from the slow ADC (hermeslite.py and Quisk agree)."""
    return (3.26 * raw / 4096 - 0.5) / 0.01


def current_a(raw: int) -> float:
    """PA current, Quisk's formula including its 1000/1270 input divider
    (module docstring: hermeslite.py omits the divider)."""
    return ((3.26 * raw / 4096) / 50) / 0.04 / (1000 / 1270)


def power_w(raw: int) -> float:
    """PROVISIONAL forward/reverse power: a square law through Quisk's
    3382 -> 4.98 W (module docstring). Replace with a measured table."""
    return 4.98 * (max(0, raw) / 3382.0) ** 2


def swr(fwd: float, rev: float, min_fwd: float = 0.05) -> float | None:
    """(1+G)/(1-G), G = sqrt(rev/fwd); None below min_fwd (noise)."""
    if fwd < min_fwd:
        return None
    g = math.sqrt(max(0.0, min(0.99, rev / fwd)))
    return (1 + g) / (1 - g)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------
def _request(cmd: int, arg: int = 0) -> bytes:
    return bytes([0xEF, 0xFE, cmd, arg]) + bytes(60) if cmd == 4 else bytes([0xEF, 0xFE, cmd]) + bytes(60)


def parse_discovery(data: bytes, addr: tuple[str, int]) -> dict | None:
    """A discovery reply (research section 2's table) as a dict, or None if
    `data` is not one."""
    if len(data) < 0x16 or data[0] != 0xEF or data[1] != 0xFE or data[2] not in (2, 3):
        return None
    if not any(data[3:0x16]):
        return None                      # a request (all zeros), heard on our own port
    major, minor, board = data[0x09], data[0x15], data[0x0A]
    d = {"ip": addr[0], "port": addr[1], "mac": ":".join(f"{b:02x}" for b in data[3:9]),
         "gatewareMajor": major, "gatewareMinor": minor, "gateware": f"{major}.{minor}",
         "board": board, "boardName": BOARD_NAMES.get(board, f"unknown board 0x{board:02x}"),
         "receivers": data[0x13] if len(data) > 0x13 else 0, "busy": data[2] == 3,
         "fixedIp": bool(data[0x0B] & 0x80), "dhcp": bool(data[0x0B] & 0x20)}
    d["problem"] = _problem(d)
    return d


def _problem(d: dict) -> str:
    where = f"{d['ip']}:{d['port']}"
    if d["board"] != BOARD_HL2:
        return (f"The radio at {where} answered as board id 0x{d['board']:02x} ({d['boardName']}), not a "
                f"Hermes-Lite 2 (0x06); this driver speaks only to a Hermes-Lite 2 running its own gateware.")
    if (d["gatewareMajor"], d["gatewareMinor"]) < MIN_GATEWARE:
        return (f"The Hermes-Lite 2 at {where} runs gateware {d['gateware']}; OpenHamShack Radio needs "
                f"{MIN_GATEWARE[0]}.{MIN_GATEWARE[1]} or later, the first that stops transmitting by itself when "
                f"the computer goes quiet. Update it with the HL2's own gateware tools (the factory image is kept "
                f"as a fallback) and try again.")
    return ""


def parse_address(address: str) -> tuple[str, int | None]:
    """'ip' or 'ip:port' -> (ip, port or None). Names are resolved."""
    a = (address or "").strip()
    if not a:
        return "", None
    host, _, port = a.rpartition(":") if a.count(":") == 1 else (a, "", "")
    try:
        p = int(port) if port else None
    except ValueError as e:
        raise DeviceError(f"hl2Address {address!r} is not an address: use ip or ip:port") from e
    try:
        ip = socket.gethostbyname(host)
    except OSError as e:
        raise DeviceError(f"hl2Address {address!r}: the name {host!r} does not resolve ({e})") from e
    return ip, p


def _broadcast_addresses() -> list[str]:
    """Each interface's IPv4 broadcast address (Linux, best effort) plus
    255.255.255.255, which the kernel sends out of the default route only."""
    out = ["255.255.255.255"]
    try:
        import fcntl
        names = [n for _, n in socket.if_nameindex()]
    except (ImportError, AttributeError, OSError):
        return out
    SIOCGIFBRDADDR = 0x8919
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for name in names:
            try:
                res = fcntl.ioctl(s.fileno(), SIOCGIFBRDADDR, struct.pack("256s", name.encode()[:15]))
            except OSError:
                continue
            b = socket.inet_ntoa(res[20:24])
            if b not in out and b != "0.0.0.0":
                out.append(b)
    return out


def discover(timeout_s: float = 1.0, address: str = "", broadcast: bool = True) -> list[dict]:
    """Find Hermes-Lite 2 radios (and say what else answered). Returns one
    dict per radio: ip, port, mac, gateware ("74.2") and its major/minor,
    board and boardName, receivers, busy (already streaming to someone),
    fixedIp/dhcp, and `problem` - an operator sentence, empty when the
    driver can use it. Never raises for "nothing there".

    Broadcast goes to port 1024 on every interface; `address` (ip or
    ip:port) is also probed directly - a radio on another subnet, or the
    emulator on a localhost port. A direct probe without a port tries 1024
    and the documented alternative 1025. With broadcast off the call
    returns as soon as the addressed radio answers."""
    targets: list[tuple[str, int]] = []
    direct: tuple[str, int | None] | None = None
    if address:
        ip, p = parse_address(address)
        direct = (ip, p)
        targets += [(ip, p)] if p else [(ip, PORT), (ip, ALT_PORT)]
    if broadcast:
        targets += [(b, PORT) for b in _broadcast_addresses()]
    found: dict[tuple[str, str], dict] = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", 0))
        for t in targets:
            try:
                s.sendto(_request(2), t)
            except OSError:
                pass                      # an interface that cannot send is just not a route to a radio
        deadline = time.monotonic() + timeout_s
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            s.settimeout(left)
            try:
                data, addr = s.recvfrom(256)
            except (socket.timeout, OSError):
                break
            d = parse_discovery(data, addr)
            if d is None:
                continue
            found.setdefault((d["ip"], d["mac"]), d)
            if not broadcast and direct and d["ip"] == direct[0]:
                break
    finally:
        s.close()
    return list(found.values())


# --------------------------------------------------------------------------
# The device
# --------------------------------------------------------------------------
class HL2Device(Device):
    kind = "hl2"
    can_tx = True
    rx_range = (0.0, 38.4e6)
    tx_range = (1.8e6, 30e6)        # what the N2ADR low-pass filters cover (160-10 m)
    # Where the engine may put the signal relative to the TX frequency. The
    # Pluto's TX LO is an analogue oscillator that leaks a carrier, so OpenHamShack
    # HAM keeps its signal a quarter of the sample rate away from it; the
    # HL2's TX "LO" is a digital NCO with nothing to leak, and its 48 kS/s TX
    # path passes only +-20 kHz - so the signal sits on the NCO (offset 0),
    # and the NCO is retuned once the dial has moved more than 18 kHz.
    tx_offset_hz = 0.0
    tx_reach_hz = 18_000.0

    def __init__(self, address: str = "", fs: float = 192_000.0, cfg: dict | None = None):
        self.address = address or ""
        self.fs = float(fs)
        self.cfg = cfg or {}
        self.lna_db = float(self.cfg.get("hl2Lna", 20.0))
        self.pa = bool(self.cfg.get("hl2Pa", True))
        self.swap_iq = bool(self.cfg.get("hl2TxSwapIQ", False))
        self.tx_latency_ms = int(self.cfg.get("hl2TxLatencyMs", TX_LATENCY_MS))
        self.ptt_hang_ms = int(self.cfg.get("hl2PttHangMs", PTT_HANG_MS))
        self.stream_timeout = float(self.cfg.get("hl2StreamTimeout", 1.0))
        self.discover_timeout = float(self.cfg.get("hl2DiscoverTimeout", 1.0))
        self.radio: dict = {}
        self.peer: tuple[str, int] | None = None
        self.sock: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.rx_hz = 0.0
        self.tx_hz = 0.0
        self.drive = 0.0
        self.step, self.iq_scale = 0, 0.0
        self.mox = False
        self.tx_on = False
        self.dec = None
        self.overruns = 0           # datagrams lost on the way (zero-filled)
        self.late = 0               # duplicates / reordered, dropped
        self.resyncs = 0
        self.reader_drops = 0       # samples discarded because nobody read them
        self.tx_underruns = 0       # EP2 frames sent short of IQ while keyed
        self.samples = 0            # receive samples delivered into the queue, zeros included
        self._tel_raw: dict[int, int] = {}
        self._tel_t = 0.0
        self._ptt_in = False
        self._error: str | None = None
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._send_lock = threading.Lock()
        self._rxq: collections.deque = collections.deque()
        self._rxq_n = 0
        self._txq = np.zeros(0, np.complex64)
        self._oneshot: collections.deque = collections.deque()
        self._open = False
        self._tx_primed = False
        self._unkeyed_sent = 0
        self._real_sent_at = 0.0    # monotonic time the last written (not padding) sample went to the radio

    # -- registers ---------------------------------------------------------------
    def _reg(self, addr: int) -> int:
        if addr == R_CONFIG:
            return config_word(int(self.fs), oc_bits(self.tx_hz if self.mox else self.rx_hz))
        if addr == R_TX_FREQ:
            return int(round(self.tx_hz)) & 0xFFFFFFFF
        if addr == R_RX1_FREQ:
            return int(round(self.rx_hz)) & 0xFFFFFFFF
        if addr == R_DRIVE:
            # Drive register only while keyed: unkeyed the radio sits at its
            # lowest step, so a stray sample could never leave at full power.
            return drive_word(self.step if self.mox else 0, self.pa)
        if addr == R_LNA:
            return lna_byte(self.lna_db)
        if addr == R_TXBUF:
            return txbuf_word(self.tx_latency_ms, self.ptt_hang_ms)
        raise KeyError(addr)

    def registers(self) -> dict[int, int]:
        """What the rotation currently sends, by address (for status and tests)."""
        return {a: self._reg(a) for a in ROTATION}

    # -- datagrams ---------------------------------------------------------------
    def _new_ep2(self):
        self._ep2 = bytearray(DGRAM)
        self._ep2[0:4] = b"\xef\xfe\x01\x02"
        for off in (8, 520):
            self._ep2[off:off + 3] = b"\x7f\x7f\x7f"
        v = np.frombuffer(self._ep2, dtype=">i2")       # writable: the buffer is a bytearray
        self._ep2_s = (v[8:260].reshape(PER_FRAME, 4), v[264:516].reshape(PER_FRAME, 4))
        self._ep2_seq = 0
        self._rot = 0

    def _send_ep2(self) -> None:
        """Build and send one EP2 datagram: two frames, each one register
        from the rotation (a pending one-shot register first) with MOX in C0
        bit 0, and 126 TX samples - queued IQ x the drive's IQ scale while
        keyed, zeros otherwise."""
        with self._send_lock:
            mox = self.mox
            iq = None
            if mox:
                with self._cond:
                    take = self._txq[:PER_DGRAM]
                    self._txq = self._txq[PER_DGRAM:]
                    if len(take):
                        self._real_sent_at = time.monotonic()
                    if len(take) < PER_DGRAM:
                        if self._tx_primed:
                            self.tx_underruns += 1
                        take = np.concatenate([take, np.zeros(PER_DGRAM - len(take), np.complex64)])
                    self._cond.notify_all()
                iq = take * np.float32(self.iq_scale)
            buf = self._ep2
            struct.pack_into(">I", buf, 4, self._ep2_seq)
            self._ep2_seq = (self._ep2_seq + 1) & 0xFFFFFFFF
            for f, off in enumerate((11, 523)):
                if self._oneshot:
                    addr, val = self._oneshot.popleft()
                else:
                    addr = ROTATION[self._rot % len(ROTATION)]
                    self._rot += 1
                    val = self._reg(addr)
                buf[off] = (addr << 1) | (1 if mox else 0)
                struct.pack_into(">I", buf, off + 1, val & 0xFFFFFFFF)
                s = self._ep2_s[f]
                if iq is None:
                    s[:, 2:] = 0
                else:
                    part = iq[f * PER_FRAME:(f + 1) * PER_FRAME]
                    re = np.clip(np.round(part.real * FULL_SCALE_TX), -32767, 32767)
                    im = np.clip(np.round(part.imag * FULL_SCALE_TX), -32767, 32767)
                    s[:, 2], s[:, 3] = (im, re) if self.swap_iq else (re, im)
            self.sock.sendto(buf, self.peer)
            if not mox:
                self._unkeyed_sent += 1

    def _command(self, run: bool) -> None:
        # Bit 0 = stream IQ. Bit 7 (disable the watchdog) is never set.
        self.sock.sendto(_request(4, 0x01 if run else 0x00), self.peer)

    # -- open / close --------------------------------------------------------------
    def _find(self) -> dict:
        if self.address:
            ip, p = parse_address(self.address)
            found = discover(self.discover_timeout, self.address, broadcast=False)
            found = [d for d in found if d["ip"] == ip and (p is None or d["port"] == p)]
            where = f"at {self.address}"
        else:
            found = discover(self.discover_timeout)
            where = "on this network"
        if not found:
            raise DeviceError(f"No Hermes-Lite 2 answered {where} on UDP port 1024 (or 1025). Check it is powered "
                              f"and has an address (about 15 s after power-on; without DHCP it falls back to "
                              f"169.254.19.221), and that no firewall drops UDP ports 1024 and 1025. A radio on "
                              f"another subnet needs its address in Settings (hl2Address).")
        good = [d for d in found if not d["problem"]]
        if not good:
            raise DeviceError(found[0]["problem"])
        d = good[0]
        if d["busy"]:
            raise DeviceError(f"The Hermes-Lite 2 at {d['ip']} is already streaming to another program (it can "
                              f"serve only one). Close the other SDR program; if it was this one a moment ago, the "
                              f"radio's watchdog frees it within a few seconds.")
        return d

    def open(self) -> None:
        if self._open:
            self.close()
        if int(self.fs) not in RATE_CODES or self.fs != int(self.fs):
            raise DeviceError(f"The Hermes-Lite 2 receives at 48, 96, 192 or 384 kS/s; hl2Rate is {self.fs:g}")
        self.radio = self._find()
        self.peer = (self.radio["ip"], self.radio["port"])
        self.n_ep2 = int(self.fs) // int(TX_FS)          # EP6 datagrams per EP2 (module docstring)
        self.batch = max(4, int(round(self.fs / PER_DGRAM / 100)))   # ~10 ms of datagrams per unpack
        self._error = None
        self._stop.clear()
        self._rxq.clear()
        self._rxq_n = 0
        self._txq = np.zeros(0, np.complex64)
        self._tx_primed = False
        self._unkeyed_sent = 0
        self.mox = self.tx_on = False
        self.step, self.iq_scale, self.drive = 0, 0.0, 0.0
        self._tel_raw = {}
        self.overruns = self.late = self.resyncs = self.reader_drops = self.tx_underruns = self.samples = 0
        self._first = threading.Event()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        except OSError:
            pass                                  # the kernel's default still works, with more drops
        s.bind(("", 0))
        s.settimeout(0.02)
        self.sock = s
        self._new_ep2()
        self._open = True
        try:
            # Configure before streaming starts: one full rotation (rate,
            # frequencies, drive at step 0, LNA, PTT hang) and the watchdog
            # explicitly enabled, MOX clear, zero IQ. Stop first in case the
            # radio was left running for us.
            self._command(False)
            self._oneshot.append((R_WATCHDOG, WATCHDOG_ENABLE))
            for _ in range(-(-len(ROTATION) // 2) + 1):
                self._send_ep2()
            self._command(True)
        except OSError as e:
            self.close()
            raise DeviceError(f"Could not reach the Hermes-Lite 2 at {self.peer[0]}: {e}") from e
        self.thread = threading.Thread(target=self._run, name="hl2-stream", daemon=True)
        self.thread.start()
        if not self._first.wait(max(1.0, self.stream_timeout)):
            err = self._error
            self.close()
            raise DeviceError(err or f"The Hermes-Lite 2 at {self.peer[0]} answered discovery but sent no receive "
                              f"data after being started. A firewall that lets the request out but drops what "
                              f"comes back is the usual cause: allow UDP ports 1024 and 1025 from the radio.")

    def close(self) -> None:
        """Unkey, stop the radio streaming, close the socket. Safe twice."""
        self.mox = False
        self.tx_on = False
        self._stop.set()
        t = self.thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=1.0)
        self.thread = None
        if self.sock is not None:
            try:
                for _ in range(2):
                    self._send_ep2()              # MOX clear, zero IQ: explicit, not left to the PTT hang
                for _ in range(2):
                    self._command(False)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        self._open = False
        with self._cond:
            self._cond.notify_all()

    # -- the socket thread ----------------------------------------------------------
    def _run(self) -> None:
        try:
            self._loop()
        except Exception as e:  # noqa: BLE001 - any failure here must unkey and reach read()
            self._fail(f"The Hermes-Lite 2 stream failed: {e}")

    def _fail(self, why: str) -> None:
        self.mox = False
        self.tx_on = False
        with self._cond:
            self._error = why
            self._txq = np.zeros(0, np.complex64)
            self._cond.notify_all()
        # Unkey explicitly. If our socket is what broke, a fresh one still
        # reaches the radio (it answers whoever spoke last, and we are stopping).
        for sock in (self.sock, None):
            try:
                if sock is None:
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                for _ in range(2):
                    self._send_ep2()
                self._command(False)
                break
            except Exception:  # noqa: BLE001 - best effort; the HL2's PTT hang is the second line
                continue

    def _loop(self) -> None:
        buf = bytearray(DGRAM * self.batch)
        mv = memoryview(buf)
        slots: list[int] = []        # output position (in datagrams, from the batch start) of each slot
        pos = 0                      # datagrams (received + lost) in this batch so far
        t_batch = 0.0
        expected: int | None = None
        total = 0                    # EP6 datagrams the radio has sent since start (lost ones too)
        ep2_sent = 0
        last = time.monotonic()
        mask = 0xFFFFFFFF
        max_gap = int(MAX_GAP_S * self.fs / PER_DGRAM)
        sock = self.sock
        while not self._stop.is_set():
            k = len(slots)
            try:
                nbytes, addr = sock.recvfrom_into(mv[k * DGRAM:(k + 1) * DGRAM], DGRAM)
            except socket.timeout:
                nbytes, addr = 0, None
            now = time.monotonic()
            if nbytes == DGRAM and addr[0] == self.peer[0] and buf[k * DGRAM:k * DGRAM + 4] == b"\xef\xfe\x01\x06":
                seq = int.from_bytes(buf[k * DGRAM + 4:k * DGRAM + 8], "big")
                gap = 0 if expected is None else (seq - expected) & mask
                if gap >= 1 << 31:
                    self.late += 1                   # duplicate or reordered: already past it
                else:
                    if gap > max_gap:
                        self.resyncs += 1
                        gap = 0
                    self.overruns += gap
                    total += gap + 1
                    if not slots:
                        t_batch = now
                    slots.append(pos + gap)
                    pos += gap + 1
                    expected = (seq + 1) & mask
                    last = now
                    due = total // self.n_ep2
                    if due - ep2_sent > CATCH_UP:
                        ep2_sent = due - CATCH_UP    # forgive a long gap's debt (module docstring)
                    while ep2_sent < due:
                        self._send_ep2()
                        ep2_sent += 1
            elif now - last > self.stream_timeout:
                raise DeviceError(f"the Hermes-Lite 2 at {self.peer[0]} stopped sending receive data "
                                  f"({now - last:.1f} s of silence). Check its power and network cable; "
                                  f"the program reconnects when it answers again")
            if slots and (len(slots) == self.batch or now - t_batch > 0.015 or nbytes == 0):
                self._unpack(buf, slots, pos)
                slots, pos = [], 0

    def _unpack(self, buf: bytearray, slots: list[int], pos: int) -> None:
        """Turn a batch of EP6 datagrams into samples (vectorised), zeros
        where datagrams were lost, and pick up the response registers."""
        k = len(slots)
        a = np.frombuffer(buf, np.uint8, count=k * DGRAM).reshape(k, DGRAM)
        frames = a[:, 8:].reshape(k, 2, 512)
        b = frames[:, :, 8:].reshape(k, 2, PER_FRAME, 8).astype(np.int32)
        i = ((b[..., 0] << 24) | (b[..., 1] << 16) | (b[..., 2] << 8)) >> 8     # sign-extended 24-bit
        q = ((b[..., 3] << 24) | (b[..., 4] << 16) | (b[..., 5] << 8)) >> 8
        iq = (i.astype(np.float32) + 1j * q.astype(np.float32)).astype(np.complex64)
        iq *= np.float32(1.0 / FULL_SCALE_RX)
        good = np.all(frames[:, :, 0:3] == 0x7F, axis=(1, 2))
        if not good.all():
            iq[~good] = 0                    # a frame that lost its sync carries nothing we can trust
        if pos == k:
            out = iq.reshape(-1)
        else:
            out = np.zeros((pos, PER_DGRAM), np.complex64)
            out[np.asarray(slots)] = iq.reshape(k, PER_DGRAM)
            out = out.reshape(-1)
        # Response registers: C0 bit 7 = ACK (0 here), bits 6:3 = address, bit 0 = PTT input.
        c = frames[good][:, :, 3:8].reshape(-1, 5).astype(np.uint32)
        if len(c):
            c0 = c[:, 0]
            data = (c[:, 1] << 24) | (c[:, 2] << 16) | (c[:, 3] << 8) | c[:, 4]
            plain = (c0 & 0x80) == 0
            raddr = (c0 >> 3) & 0xF
            tel = {}
            for ad in (0, 1, 2):
                hit = np.nonzero(plain & (raddr == ad))[0]
                if len(hit):
                    tel[ad] = int(data[hit[-1]])
            self._ptt_in = bool(c0[-1] & 1)
        else:
            tel = {}
        with self._cond:
            if tel:
                self._tel_raw.update(tel)
                self._tel_t = time.monotonic()
            self._rxq.append(out)
            self._rxq_n += len(out)
            self.samples += len(out)
            keep = int(RX_KEEP * self.fs)
            while self._rxq_n > keep and len(self._rxq) > 1:
                old = self._rxq.popleft()
                self._rxq_n -= len(old)
                self.reader_drops += len(old)
            self._first.set()
            self._cond.notify_all()

    # -- receive -------------------------------------------------------------------
    def set_rx_if(self, hz: float) -> None:
        """RX1's frequency (register 0x02); the TX NCO is not touched. The
        filter board follows on the next rotation of register 0x00."""
        hz = float(hz)
        if not self.rx_range[0] <= hz <= self.rx_range[1]:
            raise DeviceError(f"The Hermes-Lite 2 receives 0-38.4 MHz; {hz / 1e6:.4f} MHz is outside it")
        self.rx_hz = hz

    set_rx_freq = set_rx_if

    def set_lna(self, db: float) -> None:
        """Receiver gain, -12..+48 dB (register 0x0A, direct-gain encoding),
        applied to the running radio without reopening it.

        The HL2 takes 0x0A at any time: the protocol wiki ([P], "LNA Gain")
        defines bit 6 = 1 as LNA[5:0] passed straight to the AD9866, 0..60
        for -12..+48 dB, and the gateware ([GW] ad9866ctrl.v, case 6'h0a)
        compares cmd_data[6:0] with the gain it last programmed on every
        0x0A frame and, if it differs, writes the AD9866 over SPI there and
        then - streaming is never interrupted. So the value is queued as a
        one-shot for the next C&C frame rather than waiting up to a whole
        rotation (six registers, three datagrams); the rotation carries the
        same value afterwards, which the gateware ignores as unchanged."""
        self.lna_db = float(db)
        if self._open:
            self._oneshot.append((R_LNA, lna_byte(self.lna_db)))

    def read(self, n: int) -> np.ndarray:
        """n samples, complex64, full scale ~ +-1; blocks. Raises DeviceError
        if the stream failed (the engine then unkeys and reconnects)."""
        with self._cond:
            # A failed stream raises at once, not after the queue empties:
            # the engine's reconnect is what unkeys and recovers.
            while True:
                if self._error:
                    raise DeviceError(self._error)
                if not self._open:
                    raise DeviceError("The Hermes-Lite 2 is closed")
                if self._rxq_n >= n:
                    break
                self._cond.wait(0.25)
            parts, got = [], 0
            while got < n:
                x = self._rxq.popleft()
                if got + len(x) > n:
                    cut = n - got
                    self._rxq.appendleft(x[cut:])
                    x = x[:cut]
                parts.append(x)
                got += len(x)
            self._rxq_n -= n
        return parts[0] if len(parts) == 1 else np.concatenate(parts)

    # -- transmit ------------------------------------------------------------------
    def set_tx_freq(self, hz: float) -> None:
        """The TX NCO (register 0x01). While keyed, the filter board follows it."""
        hz = float(hz)
        if not self.tx_range[0] <= hz <= self.tx_range[1]:
            raise DeviceError(f"The Hermes-Lite 2's filters cover 1.8-30 MHz; it will not transmit on "
                              f"{hz / 1e6:.4f} MHz")
        self.tx_hz = hz

    def set_drive(self, x: float) -> None:
        self.drive = max(0.0, min(1.0, float(x)))
        self.step, self.iq_scale = drive_split(self.drive)

    def set_tx_gain(self, db: float) -> None:
        # The NB-style interface: a gain in dB below full.
        self.set_drive(0.0 if db <= -120 else 10 ** (min(0.0, db) / 20))

    def tx_start(self) -> None:
        if self.tx_on:
            return
        self._check()
        if int(self.fs) != int(TX_FS):
            from ..dsp.multirate import Decimator
            self.dec = Decimator(int(self.fs) // int(TX_FS))     # fresh each over: no history from the last
        else:
            self.dec = None
        with self._cond:
            self._txq = np.zeros(0, np.complex64)
        self._tx_primed = False
        self._real_sent_at = 0.0
        self.tx_on = True
        self.mox = True

    def write(self, iq: np.ndarray) -> None:
        """Queue TX IQ at `fs`; it leaves at 48 kS/s as the RX stream paces
        it. Returns once no more than TX_HIGH_WATER seconds remain queued,
        which is what paces the engine's transmit loop (the Pluto's push()
        blocks the same way)."""
        if not self.tx_on:
            raise DeviceError("Transmit is not started")
        x = np.asarray(iq, np.complex64)
        if self.dec is not None:
            x = self.dec(x)
        with self._cond:
            self._txq = np.concatenate([self._txq, x])
            self._tx_primed = True
        self._wait_queue(TX_HIGH_WATER * TX_FS, 2.0 + len(x) / TX_FS)

    def tx_finish(self) -> None:
        # The queue running dry from here on is the over ending, not an
        # underrun. Nothing is held back for a whole datagram: _send_ep2
        # pads the last one with zeros by itself.
        self._tx_primed = False

    def tx_queued(self) -> float:
        """What is queued here (up to TX_HIGH_WATER, 40 ms, when write()
        returns) and then the radio's TX buffer: tx_latency_ms (20 ms by
        default, register 0x17) behind the last written sample to leave
        here. The research (docs/ham/hl2-research.md sections 6-8) says the
        buffer is filled to that latency before output starts and that
        samples already in it carry their own PTT flag, so MOX clearing may
        well let it play out - but drive is a register, applied at once, so
        set_drive(0) would still drop those 20 ms by up to 7.5 dB, and how
        the gateware treats a FIFO when MOX drops is unverified. Keeping MOX
        and drive for the buffer's latency costs 20 ms of padding on air and
        does not depend on either."""
        if not self.tx_on:
            return 0.0
        with self._cond:
            here = len(self._txq) / TX_FS
        radio = self.tx_latency_ms / 1000.0
        if here > 0:
            return here + radio
        return max(0.0, self._real_sent_at + radio - time.monotonic())

    def _wait_queue(self, level: float, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while len(self._txq) > level:
                if self._error:
                    raise DeviceError(self._error)
                if not self.tx_on:
                    return                       # unkeyed meanwhile: nothing left to send
                if time.monotonic() > deadline:
                    raise DeviceError("The Hermes-Lite 2 stopped taking transmit samples (its receive stream, "
                                      "which paces them, has stalled)")
                self._cond.wait(0.05)

    def tx_stop(self) -> None:
        """Drive to step 0 and IQ to zero, MOX clear, queue emptied; returns
        once two unkeyed EP2s have gone and the radio's own buffer and PTT
        hang have run out, so a sequencer releasing relays after this does
        so with RF already off."""
        if not self.tx_on and not self.mox:
            return
        self.iq_scale = 0.0
        self.mox = False
        self.tx_on = False
        self.step = 0
        with self._cond:
            self._txq = np.zeros(0, np.complex64)
            self._cond.notify_all()
        mark = self._unkeyed_sent
        deadline = time.monotonic() + 0.2
        while self._unkeyed_sent < mark + 2 and time.monotonic() < deadline and self._open and not self._error:
            time.sleep(0.002)
        time.sleep((self.tx_latency_ms + self.ptt_hang_ms) / 1000.0)

    def tx_latency(self) -> float:
        """What is queued here, the radio's TX buffer, and the decimator's
        delay. Network and the AD9866 pipeline are not known (sub-ms)."""
        lat = len(self._txq) / TX_FS + self.tx_latency_ms / 1000.0 + PER_DGRAM / TX_FS
        if self.dec is not None:
            lat += self.dec.delay / self.fs
        return lat

    def tx_full_w(self, hz: float) -> float:
        if not self.tx_range[0] <= hz <= self.tx_range[1]:
            return 0.0
        return FULL_W if self.pa else RF1_W

    def _check(self) -> None:
        if self._error:
            raise DeviceError(self._error)
        if not self._open:
            raise DeviceError("The Hermes-Lite 2 is not open")

    # -- telemetry / status ------------------------------------------------------------
    def telemetry(self) -> dict:
        """From the rotating response registers: temp (deg C), fwd and rev (W,
        PROVISIONAL - see power_w), current (A), swr (None below 0.05 W), and
        the flags tx_inhibit, fifo_underflow, fifo_overflow, adc_overload;
        `age` is seconds since the last response; {} before any arrived.
        Forward and reverse are swapped if reverse reads higher: the sense
        transformer's polarity varies between units (research section 1)."""
        with self._cond:
            raw = dict(self._tel_raw)
            t = self._tel_t
        if not raw:
            return {}
        out: dict = {"age": time.monotonic() - t, "calibrated": False, "raw": raw}
        if 0 in raw:
            r0 = raw[0]
            out["tx_inhibit"] = not (r0 >> 25) & 1          # active low (module docstring)
            out["adc_overload"] = bool((r0 >> 24) & 1)
            out["fifo_underflow"] = (r0 >> 14) & 3 == 2
            out["fifo_overflow"] = (r0 >> 14) & 3 == 3
            out["firmware"] = r0 & 0xFF
        if 1 in raw:
            out["temp"] = temp_c((raw[1] >> 16) & 0xFFF)
        if 1 in raw and 2 in raw:
            f, r = power_w(raw[1] & 0xFFF), power_w((raw[2] >> 16) & 0xFFF)
            if r > f:
                f, r = r, f
            out["fwd"], out["rev"] = f, r
            out["swr"] = swr(f, r)
        if 2 in raw:
            out["current"] = current_a(raw[2] & 0xFFF)
        return out

    def status(self) -> dict:
        tel = self.telemetry()
        tel.pop("raw", None)
        return {"kind": self.kind, "address": f"{self.peer[0]}:{self.peer[1]}" if self.peer else self.address,
                "mac": self.radio.get("mac", ""), "gateware": self.radio.get("gateware", ""), "fs": self.fs,
                "rxHz": self.rx_hz, "txHz": self.tx_hz, "mox": self.mox, "drive": self.drive,
                "driveStep": self.step, "lnaDb": self.lna_db, "pa": self.pa,
                "oc": oc_bits(self.tx_hz if self.mox else self.rx_hz), "overruns": self.overruns,
                "late": self.late, "resyncs": self.resyncs, "readerDrops": self.reader_drops,
                "txUnderruns": self.tx_underruns, "error": self._error or "", "telemetry": tel}
