"""The middle beacon's text: AO-40 "uncoded" frames, both ways.

QO-100's middle beacon (10489.750 MHz, DK0SB) sends text in the block
format AMSAT designed for AO-40 (AMSAT-DL tlmspec.txt, sections 4, 5 and 7;
docs/qo100-research.md section 2):

- 400 bit/s. Each message bit is differentially encoded (a "1" is a change
  of the data stream, a "0" none), XOR-ed with the 400 Hz bit clock
  (Manchester: every bit is two half-bits of opposite sign), low-passed
  (3 dB at 560 Hz) and balanced-modulated: BPSK with no carrier.
- A block is the sync 39 15 ED 30, 512 data bytes, and a CRC of them, sent
  MSbit first, then fill bytes of #50 before the next sync (tlmspec: "~130";
  DK0SB sends a zero byte and fifty of #50, measured below).
- The CRC (tlmspec section 7): x^16 + x^12 + x^5 + 1, register preset to
  FFFF, MSByte first - gr-satellites checks it as CRC-16/CCITT-FALSE, and
  that is what a real block passes.
- The 512 bytes are ASCII: the first byte is the block type ("K", "L",
  "M", "N" are message blocks; "A" telemetry; "E" events; "D" data dumps),
  then a space. No CR/LF is sent; a line is 64 characters. Bit 7 set "may be
  used to indicate highlighted character display".

What DK0SB actually sends, from Brian's recording of 07/10/2026 12:59 UTC
(qo100-nb-2026-10-07-after-dish, 5 min, all 12 blocks decoded, none failed):
an uncoded block, its fill (00, then 50 x #50), a 5200-symbol AO-40 FEC
frame (its 65-bit distributed sync matches in full every time), the same
fill again, the next
uncoded block - one every 25.4 s, the types in turn K, L, M, N. So each
block comes round about every 100 s. The FEC frames (convolutional code,
interleaving and Reed-Solomon; gr-satellites' ao40_fec_deframer) are not
decoded here: they would give a few dB more margin on a weak dish, and
whether they carry the same text as the uncoded blocks is [unverified].

Verified on that real signal: the bit order, the polarity-free
differential decoding and the CRC variant above - none of it rests on the
simulator, which is built from this same module (modulate_bits()).

    rx = Receiver(4000.0)        # any rate that is a whole number of samples per bit (>= 4)
    for ev in rx.feed(iq):       # complex baseband, the beacon near 0 Hz
        ...                      # {"kind": "frame", "type": "K", "text": ..., "lines": [...], ...}
"""
from __future__ import annotations

import math

import numpy as np

from ohsnb.i18n import _

BAUD = 400.0
SYNC = 0x3915ED30
SYNC_BYTES = bytes([0x39, 0x15, 0xED, 0x30])
BLOCK = 512
LINE = 64
FILL = 0x50
FILL_BYTES = b"\x00" + bytes([FILL]) * 50   # after each block and FEC frame, as DK0SB sends (tlmspec: "~130")
FEC_SYMBOLS = 5200            # an AO-40 FEC frame, which DK0SB sends between uncoded blocks
FRAME_BITS = (BLOCK + 2) * 8
SYNC_ERRORS = 3               # gr-satellites' default; a false sync costs ~one an hour of noise
MAX_OFFSET_HZ = 500.0         # how far from 0 Hz the carrier is looked for
ACQ_SECONDS = 2.0             # signal looked at for each carrier search
ACQ_PEAK = 12.0               # squared line over the median of its spectrum: a beacon, not noise
LOST_SNR_DB = 2.0             # symbol SNR below which, for LOST_SECONDS, the carrier is searched for again
LOST_SECONDS = 3
REPAIR_TRIES = 8              # weakest symbols flipped, one at a time, when the CRC fails


def crc16(data: bytes) -> int:
    """The AMSAT P3 CRCC: x^16+x^12+x^5+1, preset FFFF, MSB first, no final
    XOR. A block followed by its own CRC gives 0."""
    r = 0xFFFF
    for b in data:
        r = _CRC_TABLE[((r >> 8) ^ b) & 0xFF] ^ ((r << 8) & 0xFFFF)
    return r


def _crc_table() -> list[int]:
    t = []
    for i in range(256):
        r = i << 8
        for _ in range(8):
            r = ((r << 1) ^ 0x1021) if r & 0x8000 else (r << 1)
        t.append(r & 0xFFFF)
    return t


_CRC_TABLE = _crc_table()


# --------------------------------------------------------------------------- text
def block_text(kind: str, lines: list[str]) -> bytes:
    """512 bytes the way DK0SB fills a block: the type letter and a space
    before the first line, each line blank-padded to 64 characters, at most
    eight lines, blanks after."""
    lines = list(lines)[:BLOCK // LINE] or [""]
    lines[0] = f"{kind} {lines[0]}"
    raw = "".join(line[:LINE].ljust(LINE) for line in lines).encode("ascii", "replace")
    return raw.ljust(BLOCK, b" ")


def parse_block(block: bytes) -> dict:
    """A decoded block as the UI shows it: its type, its eight lines (bit 7,
    "highlighted", cleared; anything unprintable a middle dot) and which
    characters were highlighted."""
    lines, hi = [], []
    for i in range(0, len(block), LINE):
        chunk = block[i:i + LINE]
        lines.append("".join(chr(c & 0x7F) if 32 <= (c & 0x7F) < 127 else "·" for c in chunk).rstrip())
        hi.append([j for j, c in enumerate(chunk) if c & 0x80])
    kind = chr(block[0] & 0x7F) if block and 32 <= (block[0] & 0x7F) < 127 else "?"
    return {"type": kind, "lines": lines, "highlight": hi, "text": "\n".join(lines).rstrip()}


# --------------------------------------------------------------------------- transmit
def frame_bits(block: bytes, fill: bytes = FILL_BYTES) -> np.ndarray:
    """One block on the air as message bits: sync, the 512 bytes, the CRC,
    the inter-block fill."""
    if len(block) != BLOCK:
        raise ValueError(_("a block is {block} bytes, not {got}").format(block=BLOCK, got=len(block)))
    c = crc16(block)
    raw = SYNC_BYTES + block + bytes([c >> 8, c & 0xFF]) + fill
    return np.unpackbits(np.frombuffer(raw, np.uint8))


def lowpass_fir(rate: float, cutoff_hz: float = 560.0) -> np.ndarray:
    """The beacon's "gentle low pass (3 dB point = 560 Hz)" as a
    windowed-sinc FIR about 10 ms long, unity at DC. The spec gives only
    the 3 dB point; the shape is [unverified], and this one is chosen to be
    gentle."""
    ntaps = int(0.0107 * rate) | 1
    n = np.arange(ntaps) - (ntaps - 1) / 2
    h = 2 * cutoff_hz / rate * np.sinc(2 * cutoff_hz / rate * n) * np.hamming(ntaps)
    return h / h.sum()


def modulate(blocks: list[bytes], rate: float, fill: bytes = FILL_BYTES) -> np.ndarray:
    """The beacon's baseband for `blocks` sent once each (modulate_bits)."""
    return modulate_bits(np.concatenate([frame_bits(b, fill) for b in blocks]), rate)


def modulate_bits(bits: np.ndarray, rate: float, lowpass_hz: float = 560.0) -> np.ndarray:
    """Message bits on the air at `rate` (a whole number of samples per
    half-bit), as one period of a loop: the differential encoder ends where
    it started (a fill byte of 0x40 is added when it would not) and the
    low-pass is circular, so the loop has no seam. Unit RMS, complex64."""
    spb = rate / (2 * BAUD)
    if abs(spb - round(spb)) > 1e-9 or round(spb) < 1:
        raise ValueError(_("{rate:g} Hz is not a whole number of samples per half-bit at {baud:g} bit/s").format(
            rate=rate, baud=BAUD))
    spb = int(round(spb))
    bits = np.asarray(bits, np.uint8)
    if int(bits.sum()) % 2:
        bits = np.concatenate([bits, np.unpackbits(np.array([0x40], np.uint8))])
    diff = np.bitwise_xor.accumulate(bits.astype(np.int8))
    sym = np.repeat(diff * 2 - 1, 2) * np.tile(np.array([1, -1], np.int8), len(bits))
    x = np.repeat(sym.astype(np.float64), spb)
    # The low-pass applied circularly. A frequency-domain filter would be
    # shorter to write, but a loop's length is rarely a fast FFT size: one
    # of the simulator's took a second that way.
    h = lowpass_fir(rate, lowpass_hz)
    half = len(h) // 2
    y = np.convolve(np.concatenate([x[-half:], x, x[:half]]), h, "valid")
    return (y / np.sqrt(np.mean(y ** 2))).astype(np.complex64)


# --------------------------------------------------------------------------- receive
class Receiver:
    """Demodulates and deframes the beacon from complex baseband at `rate`.

    - Carrier: BPSK has none, so it is found by squaring (a line at twice
      the offset, within +-MAX_OFFSET_HZ) over ACQ_SECONDS, then followed
      symbol by symbol by a Costas loop - the free-running LNB of 07/10
      moved the beacon 2 Hz a second, and beacon lock's own corrections
      come in steps.
    - Timing: each symbol is the Manchester matched filter (first half-bit
      minus the second); its energy over a second, per sample phase, is
      largest at the right one - half a bit out, a Manchester stream gives
      nothing where two bits are alike.
    - Bits: coherent, then differentially decoded, so the loop's 180-degree
      ambiguity does not matter.
    - Frames: the sync within SYNC_ERRORS bits, then 4112 bits whose CRC
      must pass. One that fails gets REPAIR_TRIES more chances: its weakest
      symbols flipped one at a time (a wrong symbol is two wrong message
      bits after differential decoding); the CRC then has to pass by chance
      on ~1 in 8000 broken blocks for a wrong one to get through.

    `feed()` returns events: {"kind": "frame", ...} for each good block, and
    {"kind": "bad"} for a sync whose block would not decode."""

    def __init__(self, rate: float):
        sps = rate / BAUD
        if abs(sps - round(sps)) > 1e-9 or sps < 4:
            raise ValueError(_("{rate:g} Hz is not a whole number (>= 4) of samples per bit at {baud:g} bit/s").format(
                rate=rate, baud=BAUD))
        self.rate = float(rate)
        self.sps = int(round(sps))
        h = self.sps // 2
        # Matched to the pulse as sent: the Manchester half-bits through the
        # same 560 Hz low-pass (lowpass_fir). Against a bare +1/-1 template
        # this decodes about 1 dB weaker beacons (simulated, in noise).
        rect = np.concatenate([np.ones(h), np.zeros(self.sps - 2 * h), -np.ones(h)])
        self.mf = np.convolve(rect, lowpass_fir(self.rate))
        self.mf /= np.sum(np.abs(self.mf))
        self.frames = 0
        self.failed = 0
        self.repaired = 0
        self.reset()

    def reset(self) -> None:
        """Start again from the carrier search (the caller's frequency jumped)."""
        self.state = "searching"
        self.acq: list[np.ndarray] = []
        self.acq_n = 0
        self.buf = np.zeros(0, np.complex64)
        self.pos = 0                    # next symbol's first sample, in buf
        self.nco_f = 0.0                # Hz, coarse mixer (from the search)
        self.nco_ph = 0.0
        self.theta = 0.0                # Costas loop phase (radians) and frequency (radians per symbol)
        self.dtheta = 0.0
        self.energy = np.zeros(self.sps)
        self.prev_sym = 0.0 + 0.0j
        self.prev_bit_sign = 1
        self.reg = 0
        self.nbits = 0                  # message bits produced since reset
        self.soft: list[float] = []     # recent symbols' |Re| (confidence), per message bit
        self.bits: list[int] = []
        self.pending: list[int] = []    # message-bit index where each candidate block starts
        self.snr_acc = [0.0, 0.0, 0]
        self.snr_db = 0.0
        self.freq = 0.0                 # carrier offset, Hz (search + loop)
        self.weak_s = 0

    def retune(self, delta_hz: float) -> None:
        """The channel feeding this moved `delta_hz` up (beacon lock's rxCorr
        stepping after a drifting LNB): the beacon in it moved as much
        down, at once. Taken out of the mixer, so the carrier loop never
        sees the step - left to the loop, a 3 Hz step every half second
        threw its phase about by most of a radian and lost one block in
        four on Brian's 07/10 recording. A move that puts the beacon
        outside the search range starts the search again."""
        self.nco_f -= float(delta_hz)
        self.freq = self.nco_f
        if abs(self.nco_f) > MAX_OFFSET_HZ:
            self.reset()

    # -- the stream ----------------------------------------------------------
    def feed(self, iq: np.ndarray) -> list[dict]:
        iq = np.asarray(iq, np.complex64)
        if not len(iq):
            return []
        # The mixer runs while searching too, so retune() keeps what has
        # been gathered coherent across a step.
        n = np.arange(len(iq))
        mix = np.exp(-1j * (self.nco_ph + 2 * np.pi * self.nco_f / self.rate * n)).astype(np.complex64)
        self.nco_ph = float((self.nco_ph + 2 * np.pi * self.nco_f / self.rate * len(iq)) % (2 * np.pi))
        iq = iq * mix
        if self.state == "searching":
            self.acq.append(iq)
            self.acq_n += len(iq)
            if self.acq_n < ACQ_SECONDS * self.rate:
                return []
            x = np.concatenate(self.acq)
            self.acq, self.acq_n = [], 0
            f = self._search(x)
            if f is None:
                return []
            # Found f Hz off the mixer: move the mixer there, and turn what
            # was gathered by as much (a block may start in it), the phase
            # carried on across the join.
            x = x * np.exp(-2j * np.pi * f / self.rate * np.arange(len(x))).astype(np.complex64)
            self.nco_ph = float((self.nco_ph + 2 * np.pi * f / self.rate * len(x)) % (2 * np.pi))
            self.nco_f += f
            self.freq = self.nco_f
            self.state = "tracking"
            iq = x
        self.buf = np.concatenate([self.buf, iq])
        return self._symbols()

    def _search(self, x: np.ndarray) -> float | None:
        nfft = 1 << int(np.ceil(np.log2(len(x))) + 1)
        S = np.abs(np.fft.fft(x.astype(np.complex128) ** 2, nfft))
        f = np.fft.fftfreq(nfft, 1.0 / self.rate) / 2
        inside = np.abs(f) <= MAX_OFFSET_HZ
        S_in = S[inside]
        k = int(np.argmax(S_in))
        if S_in[k] < ACQ_PEAK * np.median(S_in):
            return None
        # Parabolic interpolation between bins.
        idx = np.flatnonzero(inside)[k]
        a, b, c = S[idx - 1], S[idx], S[(idx + 1) % nfft]
        d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        return float(f[idx] + d * self.rate / nfft / 2)

    def _symbols(self) -> list[dict]:
        sps, h = self.sps, self.sps // 2
        out: list[dict] = []
        if len(self.buf) < len(self.mf) + 2 * sps:
            return out          # (and np.convolve would swap its arguments)
        # Matched filter at every sample: z[i] is the symbol starting at i.
        z = np.convolve(self.buf, self.mf[::-1], "valid")
        pos = max(self.pos, h)
        last = len(z) - (sps - h)          # a symbol needs its timing neighbours
        if pos >= last:
            self.pos = pos
            return out
        starts = np.arange(pos, last, sps)
        # Timing: energy at each sample phase around the symbols, faded over
        # about a second; the strongest phase is where symbols start.
        e = np.abs(z[starts[:, None] - h + np.arange(sps)[None, :]]) ** 2
        fade = min(1.0, len(starts) / BAUD)
        self.energy = (1 - fade) * self.energy + fade * e.mean(0)
        # Costas loop, second order, ~4 Hz loop bandwidth at 400 symbols/s.
        zeta, bn = 0.707, 4.0 / BAUD
        wn = 2 * math.pi * bn / (zeta + 1 / (4 * zeta))
        kp, ki = 2 * zeta * wn, wn * wn
        theta, dtheta, prev = self.theta, self.dtheta, self.prev_bit_sign
        sig = noise = 0.0
        for y0 in z[starts].tolist():
            y = y0 * complex(math.cos(theta), -math.sin(theta))
            re, im = y.real, y.imag
            p = re * re + im * im
            err = re * im / p if p > 0 else 0.0
            dtheta += ki * err
            theta = (theta + dtheta + kp * err) % (2 * math.pi)
            sign = 1 if re >= 0 else -1
            self._bit(1 if sign != prev else 0, abs(re), out)
            prev = sign
            sig += re * re
            noise += im * im
        self.theta, self.dtheta, self.prev_bit_sign = theta, dtheta, prev
        pos = int(starts[-1]) + sps
        # Follow the timing a sample at a time (phase h is "where we are").
        best = int(np.argmax(self.energy))
        if best != h and self.energy[best] > 1.05 * self.energy[h]:
            step = 1 if best > h else -1
            pos += step
            self.energy = np.roll(self.energy, -step)
        keep = max(0, pos - sps)
        self.buf = self.buf[keep:]
        self.pos = pos - keep
        a = self.snr_acc
        a[0] += sig
        a[1] += noise
        a[2] += len(starts)
        if a[2] >= BAUD:
            # Symbols' in-phase power over quadrature (noise only, once locked).
            self.snr_db = float(10 * np.log10(max(a[0] - a[1], 1e-12) / max(a[1], 1e-12)))
            self.snr_acc = [0.0, 0.0, 0]
            # A loop that has lost the carrier (the beacon gone, or moved
            # further at once than the loop can follow) looks again.
            self.weak_s = self.weak_s + 1 if self.snr_db < LOST_SNR_DB else 0
            if self.weak_s >= LOST_SECONDS:
                self.reset()
                return out
        # The loop's frequency moves into the mixer, so the matched filter
        # always sees the carrier near 0 Hz: a symbol is 2.5 ms, and 100 Hz
        # left in it would turn a quarter of a cycle across it.
        self.nco_f += self.dtheta * BAUD / (2 * math.pi)
        self.dtheta = 0.0
        self.freq = self.nco_f
        return out

    # -- frames ----------------------------------------------------------------
    def _bit(self, bit: int, conf: float, out: list) -> None:
        self.bits.append(bit)
        self.soft.append(conf)
        self.nbits += 1
        self.reg = ((self.reg << 1) | bit) & 0xFFFFFFFF
        if bin(self.reg ^ SYNC).count("1") <= SYNC_ERRORS:
            if not self.pending or self.nbits - self.pending[-1] > 32:
                self.pending.append(self.nbits)
        while self.pending and self.nbits - self.pending[0] >= FRAME_BITS:
            start = self.pending.pop(0)
            self._block(start, out)
        # Keep what a pending block, or the next sync, still needs.
        hold = (self.nbits - self.pending[0] + 2) if self.pending else 40
        excess = len(self.bits) - max(hold, 40)
        if excess > 4096:
            del self.bits[:excess]
            del self.soft[:excess]

    def _block(self, start: int, out: list) -> None:
        base = self.nbits - len(self.bits)
        i0 = start - base
        if i0 < 0:
            return
        bits = np.array(self.bits[i0:i0 + FRAME_BITS], np.uint8)
        raw = np.packbits(bits).tobytes()
        repaired = False
        if crc16(raw) != 0:
            raw = self._repair(bits, np.array(self.soft[i0:i0 + FRAME_BITS]))
            repaired = raw is not None
        if raw is None:
            self.failed += 1
            out.append({"kind": "bad"})
            return
        # A block this one overlapped was a false sync: drop it.
        self.pending = [p for p in self.pending if p >= start + FRAME_BITS]
        self.frames += 1
        self.repaired += int(repaired)
        ev = {"kind": "frame", "block": raw[:BLOCK], "repaired": repaired, "snr": round(self.snr_db, 1),
              "freq": round(self.freq, 2)}
        ev.update(parse_block(raw[:BLOCK]))
        out.append(ev)

    @staticmethod
    def _repair(bits: np.ndarray, conf: np.ndarray) -> bytes | None:
        # A wrong symbol k turns message bits k and k+1 (k+1 the change after it).
        for k in np.argsort(conf)[:REPAIR_TRIES]:
            b = bits.copy()
            b[k] ^= 1
            if k + 1 < len(b):
                b[k + 1] ^= 1
            raw = np.packbits(b).tobytes()
            if crc16(raw) == 0:
                return raw
        return None


__all__ = ["Receiver", "modulate", "modulate_bits", "block_text", "parse_block", "crc16", "frame_bits", "BAUD"]
