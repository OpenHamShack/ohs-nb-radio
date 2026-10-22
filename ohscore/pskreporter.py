"""PSKReporter spot upload: who this station heard, sent to
report.pskreporter.info as the IPFIX datagrams its developer page
describes (https://pskreporter.info/pskdev.html).

**Opt-in.** Nothing here runs until the operator turns on the
`pskReporter` setting, which needs a callsign and a locator (the state
registry refuses it without them): Brian's decision, docs/ham/DESIGN-HAM.md
section 12, "nothing leaves the machine until the operator turns it on".
With it off the engine never calls `offer()`, no socket is opened and no
thread is started.

**What is sent.** One receiver record - the operator's callsign, locator
and "QO-100 NB 0.1.9" / "OpenHamShack Radio 0.1.9" - and one sender record per
station heard: its callsign, the RF frequency in hertz, mode, SNR, the
slot's start time and, when the message carried one, its grid. Only
callsign-bearing decodes of FT8, FT4, Q65 and JS8 (receive) qualify -
the decoders' own `call`/`grid` fields (ohscore/modes/ft8.py
`_parse_standard`), never a guess at free text. Hashed calls ("<...>"),
low-confidence a-priori decodes and our own call are left out.

**Frequency: the RF frequency as heard, which on QO-100 is the downlink.**
The dial plus the decode's audio offset - the engine's `rxDial` is the
on-air frequency in both apps (NB: the downlink the receiver demodulates,
after the beacon lock's correction; HAM: the air side of any converter).
That is the QO-100 convention already on PSKReporter: WSJT-X operators
there run with the dial at the downlink (10489.540 MHz, as SDR Console
and most QO-100 setups present it), and OpenWebRX, which only ever hears
the downlink, reports 10489.5xx too. It is also why the frequency field
is **five bytes, not the four the developer page shows**: four bytes stop
at 4.29 GHz, so a 10489 MHz spot overflowed. PSKReporter accepted a
five-byte frequency in February 2023 for exactly this case (OpenWebRX
issue #339; WSJT-X's Network/PSKReporter.cpp has sent five ever since).
IPFIX lets the template say the length, so the server reads it.

**Batching and rate**, per the developer page: a datagram at most every
five minutes unless one fills up, the timer not aligned to the clock (a
random offset, so a thousand stations do not all send on the minute), a
callsign reported at most once per five minutes - here per callsign and
band, so a station heard on 20 m and then 40 m is two spots - and the
record templates in the first three datagrams and then again every hour.

**Never in the way.** `offer()` appends under a lock and returns; the
send - including the DNS lookup - happens on this module's own daemon
thread. A network failure is one log line, at most one per hour at
WARNING and DEBUG after that, never a toast: spotting is a courtesy to
other stations, not something the operator should be interrupted for.

**Tests never reach the real server.** The destination comes from the
constructor, then $OHS_PSKREPORTER ("host:port"; $OPENHAMSHACK_PSKREPORTER before
the rename), then the real one;
tests/scratch_home.py points the variable at a local discard port, so a
test that turns spotting on by accident sends nowhere. (The developer
page's analysing listener is report.pskreporter.info:14739, NOT the bare
pskreporter.info its page names: that name is Cloudflare, which drops
UDP silently. Results at https://pskreporter.info/cgi-bin/psk-analysis.pl.
Tried 08/10/2026: every field parsed as sent, the 5-byte frequency too;
the analyser prints SNR as an unsigned byte, so -2 shows as 254.)

No Qt and no app here, as the rest of ohscore's engine side.
"""
from __future__ import annotations

import logging
import os
import random
import re
import socket
import struct
import threading
import time
from typing import Callable

from . import callsign

log = logging.getLogger("ohscore.pskreporter")

HOST = "report.pskreporter.info"
PORT = 4739
# $OPENHAMSHACK_PSKREPORTER was its name before the OpenHamShack rename
# (17/10/2026), still read when the new one is not set.
ENV = "OHS_PSKREPORTER"
FORMER_ENV = "OPENHAMSHACK_PSKREPORTER"

# Rules from the developer page (module docstring).
INTERVAL_S = 300.0          # one datagram at most every five minutes...
JITTER_S = 30.0             # ...at a random offset, not on the clock
DEDUPE_S = 300.0            # a callsign once per five minutes (per band here)
TEMPLATE_EVERY_S = 3600.0   # templates hourly...
TEMPLATE_PACKETS = 3        # ...in this many datagrams each time
# Below the usual 1500-byte Ethernet MTU less IP/UDP headers, so a full
# datagram is never fragmented; "full" is when the next spot would not fit.
MAX_PACKET = 1400
# Spots held while the network is down: the oldest go first. An hour of a
# busy FT8 band is a few hundred; this only bounds a long outage.
MAX_PENDING = 2000

ENTERPRISE = 30351          # PSKReporter's IANA enterprise number
RX_TEMPLATE = 0x9992        # the developer page's template ids
TX_TEMPLATE = 0x9993
# Mode name as ADIF's MODE (PSKReporter's `mode` field), per decoder.
MODES = {"ft8": "FT8", "ft4": "FT4", "q65": "Q65", "js8": "JS8"}
SOURCE_AUTOMATIC = 1        # informationSource: decoded automatically

_GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$", re.IGNORECASE)

# ADIF band edges, Hz, for dedupe only (a spot's band key). Outside them a
# spot keys on its whole megahertz, which still dedupes a station heard
# twice on one frequency.
BANDS = (
    ("2190m", 135_700, 137_800), ("630m", 472_000, 479_000), ("160m", 1_800_000, 2_000_000),
    ("80m", 3_500_000, 4_000_000), ("60m", 5_060_000, 5_450_000), ("40m", 7_000_000, 7_300_000),
    ("30m", 10_100_000, 10_150_000), ("20m", 14_000_000, 14_350_000), ("17m", 18_068_000, 18_168_000),
    ("15m", 21_000_000, 21_450_000), ("12m", 24_890_000, 24_990_000), ("10m", 28_000_000, 29_700_000),
    ("8m", 40_000_000, 45_000_000), ("6m", 50_000_000, 54_000_000), ("4m", 70_000_000, 71_000_000),
    ("2m", 144_000_000, 148_000_000), ("1.25m", 222_000_000, 225_000_000), ("70cm", 420_000_000, 450_000_000),
    ("33cm", 902_000_000, 928_000_000), ("23cm", 1_240_000_000, 1_300_000_000),
    ("13cm", 2_300_000_000, 2_450_000_000), ("9cm", 3_300_000_000, 3_500_000_000),
    ("6cm", 5_650_000_000, 5_925_000_000), ("3cm", 10_000_000_000, 10_500_000_000),
    ("1.25cm", 24_000_000_000, 24_250_000_000),
)


def band(freq_hz: float) -> str:
    for name, lo, hi in BANDS:
        if lo <= freq_hz <= hi:
            return name
    return f"{int(freq_hz // 1_000_000)}MHz"


def valid_call(call: str) -> bool:
    """A callsign by ohscore/callsign.py's rule, which every part of both
    apps shares (EA8/GM4BRI/P and VE3/W1AW included)."""
    return callsign.valid(call)


def valid_locator(loc: str) -> bool:
    return bool(_GRID_RE.match((loc or "").strip()))


def destination() -> tuple[str, int]:
    """$OHS_PSKREPORTER (or $OPENHAMSHACK_PSKREPORTER) as "host:port", else the real server."""
    v = (os.environ.get(ENV, "").strip() or os.environ.get(FORMER_ENV, "").strip())
    if v:
        h, _, p = v.rpartition(":")
        try:
            return (h or "127.0.0.1"), int(p)
        except ValueError:
            log.warning("%s=%r is not host:port; spotting goes to 127.0.0.1:9", ENV, v)
            return "127.0.0.1", 9
    return HOST, PORT


# ------------------------------------------------------------------ IPFIX
def _string(s: str) -> bytes:
    # A one-byte length then UTF-8 (RFC 5101 variable length, short form),
    # cut at 254 as WSJT-X does: 255 would announce the three-byte form.
    b = (s or "").encode("utf-8")[:254]
    return bytes([len(b)]) + b


def _set(set_id: int, body: bytes) -> bytes:
    """A set: id, length (header and padding included), body null-padded to
    a multiple of four - the developer page's rule for every record set."""
    body += b"\0" * (-(len(body) + 4) % 4)
    return struct.pack(">HH", set_id, len(body) + 4) + body


def _field(element: int, length: int) -> bytes:
    return struct.pack(">HHI", 0x8000 | element, length, ENTERPRISE)


VARIABLE = 0xFFFF


def templates() -> bytes:
    """The receiver options template (set 3, one scope field, as the
    developer page's example) and the sender template (set 2): callsign,
    frequency (five bytes - module docstring), SNR, mode, locator,
    informationSource and flowStartSeconds (IANA element 150, no
    enterprise number) - WSJT-X's own field order."""
    rx = struct.pack(">HHH", RX_TEMPLATE, 3, 1) + _field(2, VARIABLE) + _field(4, VARIABLE) + _field(8, VARIABLE)
    tx = (struct.pack(">HH", TX_TEMPLATE, 7) + _field(1, VARIABLE) + _field(5, 5) + _field(6, 1)
          + _field(10, VARIABLE) + _field(3, VARIABLE) + _field(11, 1) + struct.pack(">HH", 150, 4))
    return _set(3, rx) + _set(2, tx)


def receiver_set(callsign: str, locator: str, software: str) -> bytes:
    return _set(RX_TEMPLATE, _string(callsign) + _string(locator) + _string(software))


def sender_record(spot: dict) -> bytes:
    snr = max(-128, min(127, int(round(spot["snr"]))))
    return (_string(spot["call"]) + int(spot["freq"]).to_bytes(5, "big") + struct.pack(">b", snr)
            + _string(spot["mode"]) + _string(spot.get("grid", "")) + bytes([SOURCE_AUTOMATIC])
            + struct.pack(">I", int(spot["time"]) & 0xFFFFFFFF))


def packet(export_time: float, sequence: int, domain: int, receiver: bytes, records: list[bytes],
           with_templates: bool) -> bytes:
    """One IPFIX message: version 10, length, export time, sequence (data
    records sent before this one, RFC 5101), observation domain."""
    body = (templates() if with_templates else b"") + receiver
    if records:
        body += _set(TX_TEMPLATE, b"".join(records))
    return struct.pack(">HHIII", 10, 16 + len(body), int(export_time) & 0xFFFFFFFF,
                       sequence & 0xFFFFFFFF, domain) + body


# ------------------------------------------------------------------ spotter
class Spotter:
    """Collects spots and sends them in batches. `offer()` is called from
    the decoders' threads; `poll()` decides and sends. With `thread=True`
    (the engine's) a daemon thread calls poll() every few seconds, started
    by the first spot; tests pass `thread=False`, a clock and a socket and
    call poll() themselves."""

    def __init__(self, software: str, *, dest: tuple[str, int] | None = None,
                 clock: Callable[[], float] = time.time, sock: socket.socket | None = None,
                 rng: random.Random | None = None, thread: bool = True):
        self.software = software
        self.dest = dest or destination()
        self.clock = clock
        self._sock = sock
        self.rng = rng or random.Random()
        self.thread = thread
        self.lock = threading.Lock()
        self.pending: list[dict] = []
        self.last_heard: dict[tuple[str, str], float] = {}   # (call, band) -> when last queued
        self.receiver = ("", "")
        self.domain = self.rng.getrandbits(32)
        self.sequence = 0
        self.packets = 0                 # datagrams sent this session
        self.templates_left = TEMPLATE_PACKETS
        self.templates_due: float | None = None
        self.next_send: float | None = None
        self.last_error = 0.0
        self.errors = 0
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ input
    def offer(self, ev: dict, callsign: str, locator: str) -> bool:
        """A decode event (ohscore/modes' shape, with the engine's `dial`):
        queue it as a spot if it is one. True if queued."""
        mode = MODES.get(str(ev.get("mode", "")))
        call = str(ev.get("call") or "").strip().upper()
        mine = (callsign or "").strip().upper()
        if (mode is None or ev.get("error") or ev.get("lowConfidence") or not valid_call(call)
                or call == mine or not valid_call(mine) or not valid_locator(locator) or "snr" not in ev):
            return False
        try:
            freq = float(ev.get("dial") or 0.0) + float(ev.get("df") or 0.0)
            snr = float(ev["snr"])
        except (TypeError, ValueError):
            return False
        if freq <= 0 or freq >= 2 ** 40:
            return False
        grid = str(ev.get("grid") or "").strip().upper()
        now = self.clock()
        key = (call, band(freq))
        with self.lock:
            self.receiver = (mine, locator.strip())
            seen = self.last_heard.get(key)
            if seen is not None and now - seen < DEDUPE_S:
                return False
            self.last_heard[key] = now
            if len(self.last_heard) > 4 * MAX_PENDING:
                self.last_heard = {k: t for k, t in self.last_heard.items() if now - t < DEDUPE_S}
            self.pending.append({"call": call, "freq": int(round(freq)), "snr": snr, "mode": mode,
                                 "grid": grid if valid_locator(grid) else "",
                                 "time": float(ev.get("slot") or ev.get("t") or now)})
            del self.pending[:-MAX_PENDING]
            if self.next_send is None:
                # The first datagram goes a full interval after the first
                # spot, at a random offset - batching starts as it means to go on.
                self.next_send = now + INTERVAL_S + self.rng.uniform(0.0, JITTER_S)
        if self.thread and self._worker is None:
            self._start()
        return True

    def clear(self) -> None:
        """Spotting turned off: what was waiting is dropped, not sent."""
        with self.lock:
            self.pending.clear()
            self.next_send = None

    # ------------------------------------------------------------ output
    def _full(self) -> bool:
        return self._size(self.pending) > MAX_PACKET

    def _size(self, spots: list[dict]) -> int:
        fixed = 16 + len(templates()) + len(receiver_set(*self.receiver, self.software)) + 4 + 3
        return fixed + sum(len(sender_record(s)) for s in spots)

    def poll(self) -> int:
        """Send what is due; returns the number of datagrams sent. Due means
        the interval has passed, or a datagram's worth is waiting."""
        now = self.clock()
        with self.lock:
            if not self.pending or self.next_send is None:
                return 0
            if now < self.next_send and not self._full():
                return 0
            batches = self._batches(now)
            self.next_send = now + INTERVAL_S + self.rng.uniform(0.0, JITTER_S) if self.pending else None
        sent = 0
        for data in batches:
            if self._send(data):
                sent += 1
        return sent

    def flush(self) -> int:
        """Send whatever is waiting now (the program is closing)."""
        with self.lock:
            if not self.pending:
                return 0
            self.next_send = self.clock()
        return self.poll()

    def _batches(self, now: float) -> list[bytes]:
        """Under the lock: everything pending, as datagrams of at most
        MAX_PACKET bytes. Spots that do not fit one go in the next."""
        if self.templates_due is not None and now >= self.templates_due:
            self.templates_left = TEMPLATE_PACKETS
        out = []
        rx = receiver_set(*self.receiver, self.software)
        while self.pending:
            with_t = self.templates_left > 0
            budget = MAX_PACKET - 16 - (len(templates()) if with_t else 0) - len(rx) - 4 - 3
            records, used = [], 0
            while self.pending:
                r = sender_record(self.pending[0])
                if records and used + len(r) > budget:
                    break
                records.append(r)
                used += len(r)
                self.pending.pop(0)
            out.append(packet(now, self.sequence, self.domain, rx, records, with_t))
            self.sequence += 1 + len(records)       # the receiver record and each sender record
            if with_t:
                self.templates_left -= 1
                if self.templates_left == 0:
                    self.templates_due = now + TEMPLATE_EVERY_S
        return out

    def _send(self, data: bytes) -> bool:
        try:
            if self._sock is None:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.sendto(data, self.dest)
            self.packets += 1
            return True
        except OSError as e:
            # Quiet on purpose (module docstring): one WARNING an hour, the
            # rest at DEBUG, and nothing the operator sees.
            self.errors += 1
            now = self.clock()
            level = logging.WARNING if now - self.last_error >= 3600 else logging.DEBUG
            if level == logging.WARNING:
                self.last_error = now
            log.log(level, "PSKReporter upload to %s:%s failed: %s", self.dest[0], self.dest[1], e)
            return False

    # ------------------------------------------------------------ thread
    def _start(self) -> None:
        with self.lock:
            if self._worker is not None:
                return
            self._worker = threading.Thread(target=self._run, name="ohscore-pskreporter", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while not self._stop.wait(5.0):
            try:
                self.poll()
            except Exception:  # noqa: BLE001 - a spotting bug must cost spots, never the program
                log.exception("PSKReporter spotting failed")

    def close(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
