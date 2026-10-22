"""hl2sim: a Hermes-Lite 2 emulated at the protocol level, on UDP.

It exists so that ohscore/devices/hl2.py - the code that will meet the real
radio - runs end to end without one (docs/ham/DESIGN-HAM.md 4.5 and 8.1):
discovery, start/stop, the EP6 receive stream with its framing and
sequence numbers, EP2 C&C writes and TX IQ, the rotating telemetry
responses, and the faults a real network and a real radio produce.

It is written from the same documents as the driver (docs/ham/
hl2-research.md), so it cannot catch a misreading the two share - the
TX I/Q order, the power calibration, the meaning of the TX-inhibit bit.
Those are listed in hl2.py's docstring and are settled only on hardware.

What it does, and how it decides:

- **Discovery**: a 60-byte reply as the research's table lays it out
  (board 0x06, gateware 74.2 by default, 0x03 in byte 2 while streaming).
- **Streaming** at the rate register 0x00 bits 25:24 say, from the wall
  clock, in 1032-byte EP6 datagrams of two 63-sample frames; the sequence
  number restarts at 0 on each start. It streams to whoever sent the start
  command (the HL2 keeps a single-entry address cache).
- **Signal**: noise plus a test tone at an RF frequency (`tone_hz`),
  placed relative to the RX1 frequency register, so the driver's tuning is
  checked and not just its unpacking. Another source can be plugged in
  (`source`). The sample clock runs through lost datagrams, so a tone
  stays phase-continuous across a gap, as a real radio's would.
- **Registers**: every C&C write is recorded - the latest value per
  address, a count per address, and a history of changes (not of every
  write: they repeat ~760 times a second).
- **Receive gain**: register 0x0A's LNA setting is reported (`lna_db`)
  and scales the received signal, relative to 20 dB - the driver's
  default, so a test that never touches the gain sees the levels it always
  did. A change takes effect on the next EP2 that carries it, as the
  gateware's does, so a test can tell a live change from a reopen.
- **TX**: frames with MOX set have their IQ recorded (the HL2 only queues
  TX samples while MOX is set), with each datagram's arrival time and the
  drive step then in force; MOX transitions are timestamped, and the IQ
  can be looped back into the receive stream at the right offset. The
  radio's own TX buffer (register 0x17's latency) is not modelled: the
  driver times it itself (HL2Device.tx_queued), and a test sees it as how
  long MOX and drive stay up after the last real sample arrived.
- **Telemetry** in the rotating responses (addresses 0, 1, 2): a settable
  temperature, raw forward/reverse/current values, or - by default -
  forward power simulated from the TX IQ and drive register and reverse
  power from a simulated antenna SWR. The simulated power is converted to
  raw values with the driver's own provisional curve (hl2.power_w), so
  only the round trip is tested, not the calibration.
- **Faults**: drop every k-th datagram; stall (send nothing for t seconds
  while the sample clock and sequence numbers run on - a network outage);
  and the HL2's watchdog: streaming stops if no EP2 arrives for
  `watchdog_s` (the real timeout is undocumented; 2 s here by default,
  short in tests).

Not emulated: RQST/ACK register reads, I2C, CWX, the wideband stream,
gateware update, the PTT hang (MOX is recorded per frame, which is what
the driver controls).

A whole UI session against it:

    python3 -m ohscore.devices.hl2sim --port 1024

prints its address and runs until Ctrl-C; then set device=hl2 and
hl2Address=127.0.0.1:<port> in OpenHamShack Radio's Settings.
"""
from __future__ import annotations

import argparse
import select
import socket
import threading
import time

import numpy as np

from . import hl2

RATES = {0: 48_000, 1: 96_000, 2: 192_000, 3: 384_000}
LNA_REF_DB = 20.0           # the gain at which tone_level and noise_level are what they say


def temp_raw(c: float) -> int:
    """Inverse of hl2.temp_c."""
    return int(round((c * 0.01 + 0.5) * 4096 / 3.26)) & 0xFFF


def current_raw(a: float) -> int:
    """Inverse of hl2.current_a."""
    return int(round(a * (1000 / 1270) * 0.04 * 50 * 4096 / 3.26)) & 0xFFF


def power_raw(w: float) -> int:
    """Inverse of hl2.power_w (the provisional curve), clipped to 12 bits."""
    return int(min(4095, round(3382.0 * np.sqrt(max(0.0, w) / 4.98))))


class HL2Sim:
    def __init__(self, port: int = 0, host: str = "127.0.0.1", gateware: tuple[int, int] = (74, 2),
                 board: int = 0x06, mac: bytes | None = None, receivers: int = 4,
                 tone_hz: float | None = 14_100_000.0, tone_level: float = 0.1, noise_level: float = 1e-3,
                 watchdog_s: float = 2.0, loopback: bool = False, source=None, seed: int = 1):
        self.host = host
        self.gateware = gateware
        self.board = board
        self.mac = mac or bytes([0x00, 0x1C, 0xC0, 0xA2, 0x13, (port or seed) & 0xFF])
        self.receivers = receivers
        self.tone_hz = tone_hz
        self.tone_level = tone_level
        self.noise_level = noise_level
        self.watchdog_s = watchdog_s
        self.loopback = loopback
        self.source = source
        self.rng = np.random.default_rng(seed)
        self.lock = threading.Lock()
        # what the host has written
        self.regs: dict[int, int] = {}
        self.writes: dict[int, int] = {}
        self.history: list[tuple[float, int, int]] = []
        self.mox = False
        self.mox_events: list[tuple[float, bool]] = []
        self.mox_frames = 0
        self.ep2_datagrams = 0
        self.ep2_seq_gaps = 0
        self.start_cmds: list[int] = []
        self.discovery_requests = 0
        self._tx: list[np.ndarray] = []
        self._tx_at: list[tuple[float, int]] = []     # per entry of _tx: arrival time, drive step
        # streaming
        self.streaming = False
        self.client: tuple[str, int] | None = None
        self.seq = 0                    # next EP6 sequence number (lost datagrams use one too)
        self.sent = 0
        self.dropped = 0
        self.watchdog_fired = 0
        self._drop_every = 0
        self._stall_until = 0.0
        self._sample = 0
        self._t0 = 0.0
        self._seq0 = 0
        self._rate = 48_000
        self._last_ep2 = 0.0
        self._ep2_next_seq: int | None = None
        self._resp = 0
        self._loop_buf = np.zeros(0, np.complex64)
        self._loop_phase = 0
        # telemetry
        self.temp_c = 30.0
        self.fwd_raw: int | None = None
        self.rev_raw: int | None = None
        self.current_raw_v: int | None = None
        self.antenna_swr = 1.0
        self.sim_fwd_w = 0.0
        self.tx_inhibit = False
        self.adc_overload = False
        self.fifo = None                # None, "under" or "over"
        self.ptt_in = False
        self.sock: socket.socket | None = None
        self.port = 0
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self._bind_port = port

    # -- lifecycle ---------------------------------------------------------------
    def start(self) -> "HL2Sim":
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
        except OSError:
            pass
        s.bind((self.host, self._bind_port))
        s.setblocking(False)
        self.sock = s
        self.port = s.getsockname()[1]
        self.address = f"{self.host}:{self.port}"
        self._stop.clear()
        self.thread = threading.Thread(target=self._run, name="hl2sim", daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
            self.thread = None
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def __enter__(self) -> "HL2Sim":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- controls for tests ------------------------------------------------------------
    @property
    def rate(self) -> int:
        return RATES[(self.regs.get(hl2.R_CONFIG, 0) >> 24) & 3]

    @property
    def lna_db(self) -> float | None:
        """The receive gain the host last set in register 0x0A, in dB, or
        None before it has written one. Only the direct-gain encoding
        (bit 6) is understood: the driver never sends the legacy Hermes
        step-attenuator form, so a write without bit 6 reads as None
        rather than as a guess at what the attenuator would have done."""
        v = self.regs.get(hl2.R_LNA)
        if v is None or not v & 0x40:
            return None
        return float((v & 0x3F) - 12)

    def drop_every(self, k: int) -> None:
        """Lose every k-th EP6 datagram (0: none)."""
        self._drop_every = int(k)

    def stall(self, seconds: float) -> None:
        """Send nothing for `seconds`; the sample clock and sequence run on."""
        self._stall_until = time.monotonic() + seconds

    def set_telemetry(self, temp_c: float | None = None, fwd_raw: int | None = None, rev_raw: int | None = None,
                      current_a: float | None = None, swr: float | None = None) -> None:
        """Explicit raw forward/reverse values override the simulated ones;
        `swr` sets the simulated antenna."""
        if temp_c is not None:
            self.temp_c = temp_c
        if fwd_raw is not None:
            self.fwd_raw = fwd_raw
        if rev_raw is not None:
            self.rev_raw = rev_raw
        if current_a is not None:
            self.current_raw_v = current_raw(current_a)
        if swr is not None:
            self.antenna_swr = swr

    def tx_iq(self) -> np.ndarray:
        """Every TX sample received with MOX set, normalised, at 48 kS/s."""
        with self.lock:
            return np.concatenate(self._tx) if self._tx else np.zeros(0, np.complex64)

    def tx_chunks(self) -> list[tuple[float, int, np.ndarray]]:
        """The same samples per EP2 datagram, as (arrival time, the drive
        register's step when it arrived, IQ): when the end of an over left
        the host, and at what drive."""
        with self.lock:
            return [(t, step, iq) for (t, step), iq in zip(self._tx_at, self._tx)]

    def clear_tx(self) -> None:
        with self.lock:
            self._tx = []
            self._tx_at = []

    # -- the loop --------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            r, _, _ = select.select([self.sock], [], [], 0.001)
            if r:
                for _ in range(64):
                    try:
                        data, addr = self.sock.recvfrom(2048)
                    except (BlockingIOError, InterruptedError):
                        break
                    except OSError:
                        return
                    self._incoming(data, addr)
            now = time.monotonic()
            if self.streaming and self.watchdog_s and now - self._last_ep2 > self.watchdog_s:
                self.streaming = False
                self._set_mox(False, now)
                self.watchdog_fired += 1
            if self.streaming:
                due = self._seq0 + int((now - self._t0) * self._rate / hl2.PER_DGRAM) - self.seq
                if due > 0:
                    self._emit(min(due, 256), now)

    def _incoming(self, data: bytes, addr) -> None:
        if len(data) < 3 or data[0] != 0xEF or data[1] != 0xFE:
            return
        if data[2] == 0x02 and len(data) >= 63 and not any(data[3:]):
            self.discovery_requests += 1
            self.sock.sendto(self._discovery_reply(), addr)
        elif data[2] == 0x04 and len(data) >= 4:
            cmd = data[3]
            self.start_cmds.append(cmd)
            now = time.monotonic()
            if cmd & 1:
                self.client = addr
                if not self.streaming:
                    self.seq = self._seq0 = 0
                    self._t0 = now
                    self._rate = self.rate
                self.streaming = True
                self._last_ep2 = now
            else:
                self.streaming = False
                self._set_mox(False, now)
        elif data[2] == 0x01 and len(data) == hl2.DGRAM and data[3] == 0x02:
            self._ep2(data)

    def _discovery_reply(self) -> bytes:
        r = bytearray(60)
        r[0:2] = b"\xef\xfe"
        r[2] = 0x03 if self.streaming else 0x02
        r[3:9] = self.mac
        r[0x09] = self.gateware[0]
        r[0x0A] = self.board
        r[0x13] = self.receivers
        r[0x14] = 0x40 | (self.board & 0x3F)      # 16-bit wideband format; build board id
        r[0x15] = self.gateware[1]
        return bytes(r)

    def _set_mox(self, on: bool, now: float) -> None:
        if on != self.mox:
            self.mox = on
            self.mox_events.append((now, on))

    def _ep2(self, d: bytes) -> None:
        now = time.monotonic()
        self._last_ep2 = now
        self.ep2_datagrams += 1
        seq = int.from_bytes(d[4:8], "big")
        if self._ep2_next_seq is not None and seq != self._ep2_next_seq:
            self.ep2_seq_gaps += 1
        self._ep2_next_seq = (seq + 1) & 0xFFFFFFFF
        v = np.frombuffer(d, dtype=">i2")
        frames = (v[8:260].reshape(hl2.PER_FRAME, 4), v[264:516].reshape(hl2.PER_FRAME, 4))
        keyed = []
        for f, off in enumerate((11, 523)):
            c0 = d[off]
            addr = (c0 >> 1) & 0x3F
            val = int.from_bytes(d[off + 1:off + 5], "big")
            if self.regs.get(addr) != val:
                self.history.append((now, addr, val))
                if addr == hl2.R_CONFIG and self.streaming and RATES[(val >> 24) & 3] != self._rate:
                    self._rate = RATES[(val >> 24) & 3]          # live rate change: re-anchor the clock
                    self._t0, self._seq0 = now, self.seq
            self.regs[addr] = val
            self.writes[addr] = self.writes.get(addr, 0) + 1
            mox = bool(c0 & 1)
            self._set_mox(mox, now)
            if mox:
                self.mox_frames += 1
                s = frames[f].astype(np.float32) / 32767.0
                keyed.append((s[:, 2] + 1j * s[:, 3]).astype(np.complex64))
        if keyed:
            iq = np.concatenate(keyed)
            with self.lock:
                self._tx.append(iq)
                self._tx_at.append((now, (self.regs.get(hl2.R_DRIVE, 0) >> 28) & 0xF))
            self._simulate_power(iq)
            if self.loopback:
                self._loop_in(iq)
        else:
            self.sim_fwd_w = 0.0

    def _simulate_power(self, iq: np.ndarray) -> None:
        word = self.regs.get(hl2.R_DRIVE, 0)
        full = hl2.FULL_W if word & (1 << 19) else hl2.RF1_W
        g = hl2.step_gain((word >> 28) & 0xF)
        self.sim_fwd_w = float(full * g * g * np.mean(np.abs(iq) ** 2))

    def _loop_in(self, iq: np.ndarray) -> None:
        """TX IQ (48 kS/s, at the TX frequency) into the receive stream (at
        the RX rate, relative to RX1): repeat-and-hold upsampling (crude, but
        the tone lands where it should), then a frequency shift."""
        m = self._rate // 48_000
        x = np.repeat(iq, m)
        off = self.regs.get(hl2.R_TX_FREQ, 0) - self.regs.get(hl2.R_RX1_FREQ, 0)
        n = np.arange(self._loop_phase, self._loop_phase + len(x))
        self._loop_phase += len(x)
        x = (x * np.exp(2j * np.pi * off / self._rate * n)).astype(np.complex64)
        with self.lock:
            self._loop_buf = np.concatenate([self._loop_buf, x])[-self._rate:]

    def _signal(self, n: int) -> np.ndarray:
        fs = self._rate
        rx = self.regs.get(hl2.R_RX1_FREQ, 0)
        if self.source is not None:
            x = np.asarray(self.source(n, fs, rx, self._sample), np.complex64)
        else:
            x = (self.noise_level / np.sqrt(2)) * (self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n))
            if self.tone_hz is not None and abs(self.tone_hz - rx) < fs / 2:
                k = np.arange(self._sample, self._sample + n)
                x = x + self.tone_level * np.exp(2j * np.pi * ((self.tone_hz - rx) / fs) * k)
            x = x.astype(np.complex64)
        if self.loopback:
            with self.lock:
                lb, self._loop_buf = self._loop_buf[:n], self._loop_buf[n:]
            x[:len(lb)] += lb
        g = self.lna_db
        if g is not None and g != LNA_REF_DB:
            x = x * np.float32(10 ** ((g - LNA_REF_DB) / 20))
        self._sample += n
        return x

    def _responses(self, nframes: int) -> np.ndarray:
        """C0..C4 for `nframes` frames, rotating response addresses 0, 1, 2."""
        r0 = (0 if self.tx_inhibit else 1 << 25) | ((1 << 24) if self.adc_overload else 0) | \
             ({"under": 0b10, "over": 0b11}.get(self.fifo, 0) << 14) | (self.gateware[0] & 0xFF)
        fwd = self.fwd_raw if self.fwd_raw is not None else power_raw(self.sim_fwd_w)
        if self.rev_raw is not None:
            rev = self.rev_raw
        else:
            gam = (self.antenna_swr - 1) / (self.antenna_swr + 1)
            rev = power_raw(self.sim_fwd_w * gam * gam)
        cur = self.current_raw_v if self.current_raw_v is not None else current_raw(0.2 if self.mox else 0.0)
        words = [r0, (temp_raw(self.temp_c) << 16) | (fwd & 0xFFF), ((rev & 0xFFF) << 16) | (cur & 0xFFF)]
        rows = np.array([[(a << 3) | (1 if self.ptt_in else 0), (w >> 24) & 0xFF, (w >> 16) & 0xFF,
                          (w >> 8) & 0xFF, w & 0xFF] for a, w in enumerate(words)], np.uint8)
        idx = (self._resp + np.arange(nframes)) % 3
        self._resp = (self._resp + nframes) % 3
        return rows[idx]

    def _emit(self, k: int, now: float) -> None:
        """Generate k datagrams' worth (vectorised) and send those not lost."""
        x = self._signal(k * hl2.PER_DGRAM)
        i = np.clip(np.round(x.real * hl2.FULL_SCALE_RX), -(1 << 23), (1 << 23) - 1).astype(np.int32)
        q = np.clip(np.round(x.imag * hl2.FULL_SCALE_RX), -(1 << 23), (1 << 23) - 1).astype(np.int32)
        out = np.zeros((k, hl2.DGRAM), np.uint8)
        out[:, 0:4] = (0xEF, 0xFE, 0x01, 0x06)
        seqs = (self.seq + np.arange(k, dtype=np.int64)) & 0xFFFFFFFF
        out[:, 4:8] = seqs.astype(">u4").view(np.uint8).reshape(k, 4)
        fr = out[:, 8:].reshape(k, 2, 512)
        fr[:, :, 0:3] = 0x7F
        fr[:, :, 3:8] = self._responses(2 * k).reshape(k, 2, 5)
        smp = fr[:, :, 8:].reshape(k, 2, hl2.PER_FRAME, 8)
        i = i.reshape(k, 2, hl2.PER_FRAME)
        q = q.reshape(k, 2, hl2.PER_FRAME)
        for j, sh in enumerate((16, 8, 0)):
            smp[..., j] = (i >> sh) & 0xFF
            smp[..., 3 + j] = (q >> sh) & 0xFF
        data = out.tobytes()
        stalled = now < self._stall_until
        for n in range(k):
            s = self.seq + n
            if stalled or (self._drop_every and (s + 1) % self._drop_every == 0):
                self.dropped += 1
                continue
            try:
                self.sock.sendto(data[n * hl2.DGRAM:(n + 1) * hl2.DGRAM], self.client)
                self.sent += 1
            except OSError:
                self.dropped += 1         # a full socket buffer is a lost datagram, as on a network
        self.seq += k


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Emulate a Hermes-Lite 2 on UDP (ohscore/devices/hl2sim.py).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=hl2.PORT, help="UDP port (0: any free port)")
    ap.add_argument("--tone-mhz", type=float, default=14.1, help="RF frequency of the test tone")
    ap.add_argument("--tone-level", type=float, default=0.01)
    ap.add_argument("--noise", type=float, default=1e-4)
    ap.add_argument("--watchdog", type=float, default=2.0, help="seconds without EP2 before streaming stops")
    ap.add_argument("--swr", type=float, default=1.5, help="simulated antenna SWR")
    ap.add_argument("--loopback", action="store_true", help="add our TX IQ to the receive stream")
    a = ap.parse_args(argv)
    sim = HL2Sim(port=a.port, host=a.host, tone_hz=a.tone_mhz * 1e6, tone_level=a.tone_level, noise_level=a.noise,
                 watchdog_s=a.watchdog, loopback=a.loopback)
    sim.set_telemetry(swr=a.swr)
    sim.start()
    print(f"hl2sim: Hermes-Lite 2 (gateware {sim.gateware[0]}.{sim.gateware[1]}) on {sim.address} - "
          f"in OpenHamShack Radio set device=hl2, hl2Address={sim.address}. Ctrl-C stops.", flush=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()


if __name__ == "__main__":
    main()
