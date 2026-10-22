"""KG-STV: JJ0OBZ's digital picture mode, both ways.

KG-STV (JJ0OBZ, 2010; Windows freeware, no source) is what sends the
320x240 pictures heard at 10489.6249 MHz USB on the NB transponder. Its
readme's "transmission standard" section (docs/kgstv-research.md quotes
it) gives the air interface; the rest was established on real signal -
two pictures from DL4CQ on Brian's recording of 07/10/2026, every frame
of which decodes - and by reading the program's own decoder in kgstv.exe
(build 004, the last there is). Each fact below says which.

Air interface (readme; all verified on the recording unless marked):
- 1200 baud. MSK: a 1 is 1800 Hz, a 0 1200 Hz (USB audio). 4L-FSK:
  dibits 00/01/10/11 on 1200/1400/1600/1800 Hz [unverified: never heard].
- A transmission opens with 256 bits of 0101..., then frames back to
  back: the 63-bit sync (an m-sequence), a 54-bit information chunk, and
  for some commands a data chunk.
- The information chunk is always MSK and always convolutionally coded:
  NASA K=7 (171, 133), rate 1/2, the 133 output first - 108 symbols, no
  tail. Fields, MSB first: system 4, command 4, coding 1 (1 = coded data),
  modulation 1 (1 = 4L-FSK data), block x 6, block y 6, JPEG scale index
  4, data size 12 (in bits), CRC 16.
- Every chunk's channel bits are XORed with a 127-bit m-sequence, which
  restarts at the first bit of each chunk.
- CRC: CRC-16 CCITT as the readme says; on the air it is poly 1021 with
  the register preset to 1D0F, MSB first (CRC-16/AUG-CCITT). A chunk and
  its CRC leave 0.
- Data chunk: `size` bits and its CRC. A callsign frame (command 6) is
  the callsign in ASCII, sent five times at the start and again after
  every ten blocks; command 3 (end) closes a picture, sent three times or
  more.
- Coded or 4L-FSK data chunks: how the code and the whitening combine
  with them is [unverified] - this decodes them the way the information
  chunk is done, and only a CRC that passes lets one through.

Picture (verified on the recording, and in the program's decoder):
- 300 blocks of 16x16 pixels, 20 across and 15 down; each frame carries
  one, at its (x, y), so a picture builds wherever reception starts.
- A block is one JPEG-style MCU with 2x2 chroma subsampling: four luma
  8x8 blocks (top-left, top-right, bottom-left, bottom-right), then two
  chroma blocks. The chroma order is Cr then Cb - the reverse of JPEG's:
  the other way round, Africa on DL4CQ's picture comes out blue.
- Baseline JPEG's standard (Annex K) Huffman tables and zig-zag order,
  with two differences: the DC coefficient is absolute in every block (no
  prediction), and a negative coefficient's extra bits are its magnitude
  with the top bit cleared - JPEG sends magnitude minus one, inverted. A
  standard JPEG decoder parses KG-STV's bits exactly and gets every
  negative value wrong (black comes out mid-grey).
- Quantisation: JPEG's example tables (Annex K, "quality 50") times the
  scale the 4-bit index picks from SCALES - read from kgstv.exe, where the
  decoder multiplies the tables by it. DL4CQ used index 10 (x1.0).
- The inverse DCT and YCbCr to RGB are JPEG's (JFIF); the program's own
  rounding may differ by a level or two [unverified, invisible].

    rx = Receiver(12000.0)          # complex baseband, KG-STV's 1500 Hz audio centre at 0 Hz
    for ev in rx.feed(iq): ...      # {"kind": "block", "x": 3, "y": 0, "rgb": (16, 16, 3) uint8, ...}
"""
from __future__ import annotations

import math

import numpy as np

from ..i18n.text import _

BAUD = 1200.0
CENTRE_HZ = 1500.0              # USB audio: KG-STV's tones are 1200-1800 Hz
DEV_HZ = 300.0                  # MSK: 1800 Hz is +300 from the centre, 1200 Hz -300
FSK4_HZ = (-300.0, -100.0, 100.0, 300.0)   # 4L-FSK dibits 00, 01, 10, 11 [unverified]
SYNC_BITS = "000011100001001000110110010110101110111100110001010100111111010"
WHITEN_BITS = ("1110110011000100100111001111100100000100011010101001101101001010"
               "000101100001100101111111010110111011110001110100010101110000001")
PREAMBLE_BITS = 256             # "01" repeated, before the first frame
INFO_BITS = 54
INFO_SYMBOLS = 2 * INFO_BITS
CRC_BITS = 16
G = (0o155, 0o117)              # NASA (171, 133) with the newest bit at the bottom; 133 first
SCALES = (0.07, 0.08, 0.09, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0)
COMMANDS = {0: "text", 1: "image", 2: "bsr_image", 3: "end", 4: "bsr_request", 5: "abort", 6: "callsign"}
WITH_DATA = (0, 1, 2, 6)
BLOCKS_X, BLOCKS_Y, BLOCK = 20, 15, 16
WIDTH, HEIGHT = BLOCKS_X * BLOCK, BLOCKS_Y * BLOCK
SYNC_ERRORS = 6                 # of 63: a false sync in noise is ~1 in 10^11 bits
REPAIR_TRIES = 8                # weakest bits flipped, one at a time, when a data CRC fails
MAX_OFFSET_HZ = 600.0           # how far off centre the signal may be followed

SYNC = np.array([int(c) for c in SYNC_BITS], np.uint8)
WHITEN = np.array([int(c) for c in WHITEN_BITS], np.uint8)
_SYNC_INT = int(SYNC_BITS, 2)
_MASK63 = (1 << 63) - 1


def whiten(n: int) -> np.ndarray:
    """The first `n` bits of the whitening sequence, restarted per chunk."""
    return np.resize(WHITEN, n)


# --------------------------------------------------------------------------- CRC
def crc16(bits) -> int:
    """CRC-16 over a bit array, MSB first: poly 1021, preset 1D0F. A chunk
    followed by its own CRC gives 0."""
    r = 0x1D0F
    for b in np.asarray(bits, np.uint8).tolist():
        fb = ((r >> 15) & 1) ^ b
        r = ((r << 1) & 0xFFFF) ^ (0x1021 if fb else 0)
    return r


def with_crc(bits) -> np.ndarray:
    bits = np.asarray(bits, np.uint8)
    c = crc16(bits)
    return np.concatenate([bits, _num_bits(c, 16)])


def _num_bits(v: int, n: int) -> np.ndarray:
    return np.array([(v >> (n - 1 - i)) & 1 for i in range(n)], np.uint8)


def _bits_num(bits) -> int:
    v = 0
    for b in np.asarray(bits, np.uint8).tolist():
        v = (v << 1) | b
    return v


# --------------------------------------------------------------------------- convolutional code
def _parity(x: int) -> int:
    return bin(x).count("1") & 1


_OUT = np.zeros((64, 2, 2), np.int8)      # [state, input bit] -> the two channel bits
for _st in range(64):
    for _b in range(2):
        _r = ((_st << 1) | _b) & 0x7F
        _OUT[_st, _b] = (_parity(_r & G[0]), _parity(_r & G[1]))
_SYM = (2.0 * _OUT - 1.0)                   # as +-1
_T = np.arange(64)
_PRED0, _PRED1, _TBIT = _T >> 1, (_T >> 1) | 32, _T & 1


def conv_encode(bits) -> np.ndarray:
    """Rate 1/2, K=7, from state 0, no tail (the information chunk has none)."""
    st, out = 0, []
    for b in np.asarray(bits, np.uint8).tolist():
        out.extend(_OUT[st, b].tolist())
        st = ((st << 1) | b) & 63
    return np.array(out, np.uint8)


def viterbi(soft: np.ndarray) -> tuple[np.ndarray, float]:
    """Soft symbols (positive = 1), in pairs, to the most likely bits from
    state 0. Returns the bits and how well the best path agrees with the
    symbols: 1.0 is every symbol on its path, 0 is chance."""
    soft = np.asarray(soft, np.float64).reshape(-1, 2)
    n = len(soft)
    pm = np.full(64, 1e18)
    pm[0] = 0.0
    prev = np.zeros((n, 64), np.int8)
    for i in range(n):
        cand = pm[:, None] - (_SYM * soft[i]).sum(-1)       # [state, bit] cost
        c0 = cand[_PRED0, _TBIT]
        c1 = cand[_PRED1, _TBIT]
        sel = c1 < c0
        pm = np.where(sel, c1, c0)
        prev[i] = sel
    st = int(np.argmin(pm))
    best = float(pm[st])
    out = np.zeros(n, np.uint8)
    for i in range(n - 1, -1, -1):
        out[i] = st & 1
        st = (st >> 1) | (32 if prev[i, st] else 0)
    scale = float(np.abs(soft).sum()) or 1.0
    return out, -best / scale


# --------------------------------------------------------------------------- information chunk
def pack_info(com: int, x: int = 0, y: int = 0, size: int = 0, sc: int = 10, coded: int = 0, fsk4: int = 0,
              sys: int = 0) -> np.ndarray:
    bits = np.concatenate([_num_bits(sys, 4), _num_bits(com, 4), _num_bits(coded, 1), _num_bits(fsk4, 1),
                           _num_bits(x, 6), _num_bits(y, 6), _num_bits(sc, 4), _num_bits(size, 12)])
    return with_crc(bits)


def unpack_info(bits) -> dict:
    b = np.asarray(bits, np.uint8)
    return {"sys": _bits_num(b[0:4]), "com": _bits_num(b[4:8]), "coded": int(b[8]), "fsk4": int(b[9]),
            "x": _bits_num(b[10:16]), "y": _bits_num(b[16:22]), "sc": _bits_num(b[22:26]),
            "size": _bits_num(b[26:38]), "ok": crc16(b[:INFO_BITS]) == 0}


# --------------------------------------------------------------------------- the picture codec
def _huff(bits: list[int], vals: bytes) -> tuple[dict, dict]:
    dec, enc, code, k = {}, {}, 0, 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            dec[(length, code)] = vals[k]
            enc[vals[k]] = (length, code)
            k += 1
            code += 1
        code <<= 1
    return dec, enc


# JPEG Annex K.3 (the program carries the same tables).
_DC_L = _huff([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0], bytes(range(12)))
_DC_C = _huff([0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0], bytes(range(12)))
_AC_L = _huff([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D], bytes.fromhex(
    "01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a"
    "3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a929394"
    "95969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8"
    "e9eaf1f2f3f4f5f6f7f8f9fa"))
_AC_C = _huff([0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77], bytes.fromhex(
    "000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a262728"
    "292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a92"
    "939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7"
    "e8e9eaf2f3f4f5f6f7f8f9fa"))
ZIGZAG = np.array([0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20,
                   13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52,
                   45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63])
Q_LUMA = np.array([16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
                   14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113,
                   92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99], float).reshape(8, 8)
Q_CHROMA = np.full((8, 8), 99.0)
Q_CHROMA[:4, :4] = [[17, 18, 24, 47], [18, 21, 26, 66], [24, 26, 56, 99], [47, 66, 99, 99]]
# The DCT basis: C[k, n] = a(k) cos((2n+1) k pi / 16); pixels = C.T @ F @ C.
_C = np.array([[(math.sqrt(1 / 8) if k == 0 else 0.5) * math.cos((2 * n + 1) * k * math.pi / 16)
                for n in range(8)] for k in range(8)])
LUMA_AT = ((0, 0), (0, 8), (8, 0), (8, 8))


class _Reader:
    def __init__(self, bits):
        self.b = np.asarray(bits, np.uint8).tolist()
        self.i = 0

    def get(self, n: int) -> int:
        if self.i + n > len(self.b):
            raise ValueError(_("block data ran out"))
        v = 0
        for k in range(n):
            v = (v << 1) | self.b[self.i + k]
        self.i += n
        return v

    def huff(self, table: dict) -> int:
        code = 0
        for length in range(1, 17):
            code = (code << 1) | self.get(1)
            v = table.get((length, code))
            if v is not None:
                return v
        raise ValueError(_("not a Huffman code"))


def _extend(v: int, n: int) -> int:
    """KG-STV's extra bits: top bit set, the value; clear, minus (value + 2^(n-1))."""
    if n == 0:
        return 0
    return v if v >> (n - 1) else -(v + (1 << (n - 1)))


def _extra(v: int) -> tuple[int, int]:
    """The inverse of _extend: (bit count, bits)."""
    if v == 0:
        return 0, 0
    n = abs(v).bit_length()
    return n, (v if v > 0 else -v - (1 << (n - 1)))


def decode_mcu(bits) -> list[np.ndarray]:
    """A block's data chunk (CRC removed) to its six quantised coefficient
    blocks, natural order: four luma, Cr, Cb. Raises ValueError if the bits
    do not parse exactly into six blocks."""
    rd = _Reader(bits)
    out = []
    for i in range(6):
        dc, ac = (_DC_L[0], _AC_L[0]) if i < 4 else (_DC_C[0], _AC_C[0])
        c = np.zeros(64, np.int32)
        n = rd.huff(dc)
        if n > 11:
            raise ValueError(_("bad DC size"))
        c[0] = _extend(rd.get(n), n)
        k = 1
        while k < 64:
            rs = rd.huff(ac)
            r, s = rs >> 4, rs & 15
            if s == 0:
                if r == 15:
                    k += 16
                    continue
                break
            k += r
            if k > 63:
                raise ValueError(_("coefficient past the end of a block"))
            c[k] = _extend(rd.get(s), s)
            k += 1
        blk = np.zeros(64, np.int32)
        blk[ZIGZAG] = c
        out.append(blk.reshape(8, 8))
    if rd.i != len(rd.b):
        raise ValueError(_("{n} bits left over after six blocks").format(n=len(rd.b) - rd.i))
    return out


def encode_mcu(blocks: list[np.ndarray]) -> np.ndarray:
    out: list[int] = []

    def put(n: int, v: int):
        out.extend((v >> (n - 1 - i)) & 1 for i in range(n))

    for i, blk in enumerate(blocks):
        dc, ac = (_DC_L[1], _AC_L[1]) if i < 4 else (_DC_C[1], _AC_C[1])
        z = np.asarray(blk, np.int64).reshape(64)[ZIGZAG].tolist()
        n, v = _extra(int(z[0]))
        put(*dc[n])
        put(n, v)
        run = 0
        last = max([k for k in range(1, 64) if z[k]], default=0)
        for k in range(1, last + 1):
            if z[k] == 0:
                run += 1
                continue
            while run > 15:
                put(*ac[0xF0])
                run -= 16
            n, v = _extra(int(z[k]))
            put(*ac[(run << 4) | n])
            put(n, v)
            run = 0
        if last < 63:
            put(*ac[0x00])
    return np.array(out, np.uint8)


def render_mcu(blocks: list[np.ndarray], sc: int) -> np.ndarray:
    """Six coefficient blocks to 16x16 RGB (uint8)."""
    s = SCALES[sc]
    ql, qc = Q_LUMA * s, Q_CHROMA * s
    y = np.empty((16, 16))
    for blk, (r, c) in zip(blocks[:4], LUMA_AT):
        y[r:r + 8, c:c + 8] = _C.T @ (blk * ql) @ _C + 128.0
    up = np.ones((2, 2))
    cr = np.kron(_C.T @ (blocks[4] * qc) @ _C, up)
    cb = np.kron(_C.T @ (blocks[5] * qc) @ _C, up)
    rgb = np.stack([y + 1.402 * cr, y - 0.344136 * cb - 0.714136 * cr, y + 1.772 * cb], -1)
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)


def decode_block(bits, sc: int) -> np.ndarray:
    return render_mcu(decode_mcu(bits), sc)


def encode_block(rgb: np.ndarray, sc: int) -> np.ndarray:
    """16x16 RGB to a block's data bits (no CRC), as KG-STV codes it."""
    p = np.asarray(rgb, np.float64)
    r, g, b = p[..., 0], p[..., 1], p[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b - 128.0
    cb = -0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 0.5 * r - 0.418688 * g - 0.081312 * b

    def sub(a):
        return a.reshape(8, 2, 8, 2).mean((1, 3))

    s = SCALES[sc]
    blocks = [np.rint((_C @ y[rr:rr + 8, cc:cc + 8] @ _C.T) / (Q_LUMA * s)).astype(np.int32) for rr, cc in LUMA_AT]
    blocks += [np.rint((_C @ sub(a) @ _C.T) / (Q_CHROMA * s)).astype(np.int32) for a in (cr, cb)]
    for blk in blocks:
        np.clip(blk, -2047, 2047, out=blk)
    return encode_mcu(blocks)


# --------------------------------------------------------------------------- transmit
# Sending is built from the same tables and layout the receiver reads, so
# each part below is the inverse of one above (ohscore/modes/kgstv.py turns
# a picture into an over with them; the simulator's station uses them too).
MAX_DATA_BITS = (1 << 12) - 1   # the information chunk's size field is 12 bits


def frame_bits(com: int, data=None, x: int = 0, y: int = 0, sc: int = 10) -> np.ndarray:
    """One MSK, uncoded frame as channel bits: sync, the information chunk
    (coded and whitened), the data chunk and its CRC (whitened)."""
    data = np.zeros(0, np.uint8) if data is None else np.asarray(data, np.uint8)
    info = conv_encode(pack_info(com, x, y, len(data), sc)) ^ whiten(INFO_SYMBOLS)
    parts = [SYNC, info]
    if com in WITH_DATA:
        d = with_crc(data)
        parts.append(d ^ whiten(len(d)))
    return np.concatenate(parts)


def text_bits(s: str) -> np.ndarray:
    return np.unpackbits(np.frombuffer(s.encode("shift_jis", "replace"), np.uint8))


def preamble_bits() -> np.ndarray:
    """The 256 bits of 0101... a transmission opens with."""
    return np.tile(np.array([0, 1], np.uint8), PREAMBLE_BITS // 2)


def block_data(rgb: np.ndarray, sc: int) -> tuple[np.ndarray, int]:
    """A 16x16 block's data bits and the scale index they were coded at:
    `sc`, or the first coarser one whose bits fit the size field. Each
    frame carries its own index, so one block that would not fit (busy
    detail at a fine scale: never seen at index 8 or coarser on real
    pictures, ~2.8 kbit at most for noise at index 0) is coarsened alone
    rather than the whole picture. Raises ValueError if even index 15 is
    too big, which no 16x16 block of 8-bit pixels reaches."""
    for s in range(sc, len(SCALES)):
        data = encode_block(rgb, s)
        if len(data) <= MAX_DATA_BITS:
            return data, s
    raise ValueError(_("a picture block does not fit a KG-STV frame at any quality"))


def picture_frames(call: str, rgb: np.ndarray, sc: int = 10, call_repeats: int = 5, call_every: int = 10,
                   end_repeats: int = 3) -> list[dict]:
    """A whole picture as KG-STV sends one (laid out as DL4CQ's on the
    recording), after the preamble: the callsign `call_repeats` times, the
    300 blocks left to right and top to bottom with the callsign again
    after every `call_every`, then the end frame `end_repeats` times.

    Each frame is {"com", "x", "y", "sc", "data" (bits, or None), "bits"
    (the channel bits)}, in the order they are sent."""
    rgb = np.asarray(rgb, np.uint8)
    if rgb.shape != (HEIGHT, WIDTH, 3):
        raise ValueError(_("a picture is {height}x{width} RGB").format(height=HEIGHT, width=WIDTH))
    cdata = text_bits(call)
    if len(cdata) > MAX_DATA_BITS:
        raise ValueError(_("a KG-STV callsign line is at most {n} characters").format(n=MAX_DATA_BITS // 8))
    cs = {"com": 6, "x": 0, "y": 0, "sc": sc, "data": cdata, "bits": frame_bits(6, cdata, sc=sc)}
    out = [cs] * call_repeats
    n = 0
    for by in range(BLOCKS_Y):
        for bx in range(BLOCKS_X):
            blk = rgb[by * BLOCK:(by + 1) * BLOCK, bx * BLOCK:(bx + 1) * BLOCK]
            data, s = block_data(blk, sc)
            out.append({"com": 1, "x": bx, "y": by, "sc": s, "data": data, "bits": frame_bits(1, data, bx, by, s)})
            n += 1
            if n % call_every == 0 and n < BLOCKS_X * BLOCKS_Y:
                out.append(cs)
    end = {"com": 3, "x": BLOCKS_X, "y": BLOCKS_Y, "sc": sc, "data": None,
           "bits": frame_bits(3, x=BLOCKS_X, y=BLOCKS_Y, sc=sc)}
    return out + [end] * end_repeats


def transmission_bits(call: str, rgb: np.ndarray, sc: int = 10, call_repeats: int = 5, call_every: int = 10,
                      end_repeats: int = 3) -> np.ndarray:
    """A whole picture's channel bits: the preamble, then picture_frames."""
    frames = picture_frames(call, rgb, sc, call_repeats, call_every, end_repeats)
    return np.concatenate([preamble_bits()] + [f["bits"] for f in frames])


def modulate(bits, rate: float) -> np.ndarray:
    """MSK channel bits as complex baseband, KG-STV's 1500 Hz centre at
    0 Hz: continuous phase, +-300 Hz, unit amplitude, complex64."""
    sps = rate / BAUD
    if abs(sps - round(sps)) > 1e-9:
        raise ValueError(_("{rate:g} Hz is not a whole number of samples per bit").format(rate=rate))
    f = np.repeat(np.where(np.asarray(bits, np.uint8) > 0, DEV_HZ, -DEV_HZ), int(round(sps)))
    ph = 2 * np.pi * np.cumsum(f) / rate
    return np.exp(1j * ph).astype(np.complex64)


# --------------------------------------------------------------------------- receive
class Receiver:
    """Frames from complex baseband at `rate` (at least 4 samples a bit;
    a whole number is not needed), KG-STV's centre near 0 Hz, low-passed to
    about +-1.2 kHz (the channel's job: the discriminator takes whatever
    noise it is given).

    - Demodulation: an FM discriminator, integrated over a bit (the matched
      filter for FSK's flat-topped frequency pulse).
    - Timing: a Gardner loop, one step a bit. The sender's clock is a sound
      card's, and on the recording a fixed phase lost a few blocks a
      picture to the drift by the end of one.
    - Centre: each sync word, whose bits are known, says where the centre
      and the deviation are; the next frame is sliced against them.
    - Frames: the sync within SYNC_ERRORS bits, then the information chunk
      through the Viterbi decoder; its CRC must pass. Then the data chunk,
      whose CRC must pass too - a failure is retried with each of its
      REPAIR_TRIES weakest bits flipped (a wrong block then gets through
      about once in 8000 failures).

    `feed()` returns events, one per frame: {"kind": "frame", "com": ...,
    "x", "y", "sc", "data" (bits, for commands with data) ...}, or
    {"kind": "bad", "where": "info" | "data", ...} for one heard that did
    not decode. Pictures are put together from them by Pictures."""

    def __init__(self, rate: float):
        sps = rate / BAUD
        if sps < 4:
            raise ValueError(_("{rate:g} Hz is fewer than 4 samples a bit at {baud:g} baud").format(rate=rate, baud=BAUD))
        self.rate = float(rate)
        self.sps = sps                  # samples a bit (the bit clock steps by this)
        self.box = int(round(sps))      # the integrate-over-a-bit filter's length
        self.frames = 0
        self.lost = 0
        self.repaired = 0
        self.samples = 0                # fed since construction
        self.reset()

    def reset(self) -> None:
        self.last = 0j                  # the sample before the next, for the discriminator
        self.d = np.zeros(0)            # discriminator output (Hz) not yet behind the bit clock
        self.d0 = 0                     # stream index of d[0]
        self.t = float(self.sps)        # next bit's (float) position in the integrated stream
        self.y_prev = 0.0
        self.centre = 0.0               # Hz: where the signal's middle is
        self.dev = DEV_HZ               # Hz: its deviation, as the last sync measured it
        self.soft: list[float] = []     # bits since `base`, Hz off centre
        self.base = 0                   # bit number of soft[0]
        self.nbits = 0
        self.reg = 0
        self.state = "hunt"
        self.at = 0                     # bit number where the chunk being gathered starts
        self.need = 0
        self.info: dict | None = None
        self.snr_db = 0.0
        self.heard = 0.0                # stream time (s) of the last sync
        self.mean = 0.0                 # Hz: the discriminator's recent average (AFC between frames)
        self.sync_bit = 0               # bit number of the last sync

    @property
    def freq(self) -> float:
        return self.centre

    def retune(self, delta_hz: float) -> None:
        """The channel moved `delta_hz` up: the signal in it moved down."""
        self.centre -= float(delta_hz)
        if abs(self.centre) > MAX_OFFSET_HZ:
            self.centre = 0.0

    # -- the stream ----------------------------------------------------------
    def feed(self, iq) -> list[dict]:
        iq = np.asarray(iq, np.complex64)
        if not len(iq):
            return []
        x = np.concatenate([[self.last], iq])
        self.last = complex(iq[-1])
        d = np.angle(x[1:] * np.conj(x[:-1])) * (self.rate / (2 * np.pi))
        self.d = np.concatenate([self.d, d])
        self.samples += len(iq)
        out: list[dict] = []
        sps, box = self.sps, self.box
        # z[i]: the mean over d[i:i+box]; the bit centred at i + box/2.
        if len(self.d) < box + 2:
            return out
        cs = np.concatenate([[0.0], np.cumsum(self.d)])
        z = (cs[box:] - cs[:-box]) / box
        t, half = self.t, sps / 2.0
        last = len(z) - 2
        gain = 0.08 * sps
        y_prev = self.y_prev
        while t < last:
            i = int(t)
            f = t - i
            y = z[i] * (1 - f) + z[i + 1] * f
            tm = t - half
            j = int(tm)
            fm = tm - j
            ym = z[j] * (1 - fm) + z[j + 1] * fm if j >= 0 else y
            y -= self.centre
            ym -= self.centre
            # Gardner: the mid-point between two bits is zero when the clock is right.
            dev2 = self.dev * self.dev
            e = ym * (y_prev - y) / dev2 if dev2 > 0 else 0.0
            e = max(-1.0, min(1.0, e))
            self._bit(float(y), out)
            y_prev = y
            t += sps + gain * e
        self.y_prev = y_prev
        # Keep what the next bit and its mid-point need.
        keep = max(0, int(t - sps) - 1)
        self.d = self.d[keep:]
        self.d0 += keep
        self.t = t - keep
        return out

    # -- frames ----------------------------------------------------------------
    def _bit(self, s: float, out: list) -> None:
        # Whitened data is as much mark as space, so the average of a few
        # hundred bits is the centre. Only used when frames stop syncing:
        # on 07/10 DG8RP's signal jumped 700 Hz and came back over 12 s, and
        # a centre that only the sync words move never caught up.
        self.mean += (s + self.centre - self.mean) / 128.0
        if self.state == "hunt" and self.nbits - self.sync_bit > 256 and abs(self.mean - self.centre) > 60.0:
            self.centre = max(-MAX_OFFSET_HZ, min(MAX_OFFSET_HZ, self.mean))
            self.sync_bit = self.nbits
        self.soft.append(s)
        self.nbits += 1
        self.reg = ((self.reg << 1) | (1 if s > 0 else 0)) & _MASK63
        if self.state == "hunt":
            if self.nbits >= 63 and bin(self.reg ^ _SYNC_INT).count("1") <= SYNC_ERRORS:
                self._synced()
        elif self.nbits - self.at >= self.need:
            if self.state == "info":
                self._info(out)
            else:
                self._data(out)
        if self.state == "hunt":
            excess = len(self.soft) - 64
            if excess > 4096:
                del self.soft[:excess]
                self.base += excess

    def _chunk(self, n: int) -> np.ndarray:
        i = self.at - self.base
        return np.array(self.soft[i:i + n])

    def _synced(self) -> None:
        # The sync's own bits say where the centre and the deviation are.
        s = np.array(self.soft[-63:]) + self.centre
        sign = 2.0 * SYNC - 1.0
        dev = float(np.mean(s * sign))
        if dev > 0.3 * DEV_HZ:
            centre = float(np.mean(s - dev * sign))
            if abs(centre) <= MAX_OFFSET_HZ:
                self.centre, self.dev = centre, dev
                resid = s - centre - dev * sign
                self.snr_db = float(10 * np.log10(dev * dev / max(float(np.mean(resid ** 2)), 1e-9)))
        self.heard = self.samples / self.rate
        self.sync_bit = self.nbits
        self.state, self.at, self.need = "info", self.nbits, INFO_SYMBOLS

    def _info(self, out: list) -> None:
        soft = self._chunk(INFO_SYMBOLS) / self.dev
        soft = np.where(whiten(INFO_SYMBOLS) > 0, -soft, soft)
        bits, _ = viterbi(soft)
        info = unpack_info(bits)
        if not info["ok"]:
            self.lost += 1
            out.append({"kind": "bad", "where": "info", "t": round(self.heard, 3)})
            self.state = "hunt"
            return
        self.info = info
        n = info["size"] + CRC_BITS if info["com"] in WITH_DATA else 0
        if n == 0:
            self._emit(info, None, out)
            self.state = "hunt"
            return
        if info["coded"]:
            n *= 2
        if info["fsk4"]:
            n = (n + 1) // 2
        self.state, self.at, self.need = "data", self.nbits, n
        self._trim()

    def _trim(self) -> None:
        # Drop what is before the chunk being gathered.
        drop = self.at - self.base - 64
        if drop > 0:
            del self.soft[:drop]
            self.base += drop

    def _data(self, out: list) -> None:
        info = self.info
        self.state = "hunt"
        n = info["size"] + CRC_BITS
        soft = self._chunk(self.need) / self.dev
        if info["fsk4"]:
            # [unverified] Each symbol two bits, MSB first, from four levels.
            lv = np.clip(soft * DEV_HZ, -400, 400)
            hi = (lv > 0).astype(np.uint8)
            lo = (np.abs(lv) > 200.0).astype(np.uint8) ^ (1 - hi)      # 00 -300, 01 -100, 10 +100, 11 +300
            hard = np.stack([hi, lo], 1).reshape(-1)
            conf = np.repeat(np.abs(np.abs(lv) - 200.0), 2)
            soft = (2.0 * hard - 1.0) * conf / 100.0
        if info["coded"]:
            m = 2 * n
            sym = soft[:m]
            sym = np.where(whiten(m) > 0, -sym, sym)
            bits, _ = viterbi(sym)
            conf = None
        else:
            sym = soft[:n]
            bits = (sym > 0).astype(np.uint8) ^ whiten(n)
            conf = np.abs(sym)
        ok = crc16(bits) == 0
        repaired = False
        if not ok and conf is not None:
            for k in np.argsort(conf)[:REPAIR_TRIES]:
                b = bits.copy()
                b[k] ^= 1
                if crc16(b) == 0:
                    bits, ok, repaired = b, True, True
                    break
        if not ok:
            self.lost += 1
            out.append({"kind": "bad", "where": "data", "com": info["com"], "x": info["x"], "y": info["y"],
                        "t": round(self.heard, 3)})
            return
        self.repaired += int(repaired)
        self._emit(info, bits[:info["size"]], out, repaired)

    def _emit(self, info: dict, data, out: list, repaired: bool = False) -> None:
        self.frames += 1
        ev = {"kind": "frame", "command": COMMANDS.get(info["com"], f"command {info['com']}"),
              "repaired": repaired, "snr": round(self.snr_db, 1), "freq": round(self.centre, 1),
              "t": round(self.heard, 3), "mode": mode_name(info)}
        ev.update({k: info[k] for k in ("com", "x", "y", "sc", "coded", "fsk4", "size")})
        if data is not None:
            ev["data"] = data
        out.append(ev)


def mode_name(info: dict) -> str:
    return ("4L-FSK" if info.get("fsk4") else "MSK") + ("/CONV" if info.get("coded") else "/NORM")


def text_of(data) -> str:
    raw = np.packbits(np.asarray(data, np.uint8)).tobytes() if len(data) else b""
    if len(data) % 8:
        raw = raw[:-1]
    return raw.decode("shift_jis", "replace")


# --------------------------------------------------------------------------- pictures
class Pictures:
    """Puts frames together into pictures, as the program does: a picture
    starts with its first block, takes blocks (and later repeats of missed
    ones, "BSR") wherever they fall, and is finished by the end or abort
    frame, by a block for a place it already has, or by TIMEOUT_S with no
    frame at all (the program's default time-out).

    `frame(ev)` takes a Receiver event and returns what changed:
    {"kind": "start" | "block" | "done" | "call" | "text", ...}."""

    TIMEOUT_S = 30.0

    def __init__(self):
        self.pic: dict | None = None
        self.call = ""
        self.n = 0
        self.last_t = 0.0

    def _new(self, t: float) -> dict:
        self.n += 1
        self.pic = {"id": self.n, "rgb": np.zeros((HEIGHT, WIDTH, 3), np.uint8),
                    "have": np.zeros((BLOCKS_Y, BLOCKS_X), bool), "bad": 0, "call": self.call, "t0": t,
                    "mode": "", "sc": 10}
        return self.pic

    def _done(self, why: str) -> list[dict]:
        p, self.pic = self.pic, None
        if p is None:
            return []
        return [{"kind": "done", "id": p["id"], "why": why, "call": p["call"], "rgb": p["rgb"],
                 "blocks": int(p["have"].sum()), "bad": p["bad"], "mode": p["mode"], "t0": p["t0"]}]

    def tick(self, t: float) -> list[dict]:
        """Stream time `t` (s): a picture with nothing for TIMEOUT_S is done."""
        if self.pic is not None and t - self.last_t > self.TIMEOUT_S:
            return self._done("timeout")
        return []

    def frame(self, ev: dict) -> list[dict]:
        t = float(ev.get("t", self.last_t))
        out = self.tick(t)
        self.last_t = t
        if ev["kind"] == "bad":
            if self.pic is not None and ev.get("where") == "data" and ev.get("com") in (1, 2):
                self.pic["bad"] += 1
            return out
        com = ev["com"]
        if com == 6:
            call = text_of(ev["data"]).strip()
            if call != self.call:
                self.call = call
                out.append({"kind": "call", "call": call})
            if self.pic is not None and not self.pic["call"]:
                self.pic["call"] = call
            return out
        if com == 0:
            out.append({"kind": "text", "text": text_of(ev["data"]), "call": self.call})
            return out
        if com in (3, 5):
            return out + self._done("end" if com == 3 else "abort")
        if com not in (1, 2):
            return out
        x, y = ev["x"], ev["y"]
        if x >= BLOCKS_X or y >= BLOCKS_Y:
            return out
        try:
            rgb = decode_block(ev["data"], ev["sc"])
        except ValueError:
            if self.pic is not None:
                self.pic["bad"] += 1
            return out
        p = self.pic
        if p is not None and com == 1 and p["have"][y, x]:
            out += self._done("restart")
            p = None
        if p is None:
            if com == 2:
                return out          # a repeat for a picture we never had
            p = self._new(t)
            out.append({"kind": "start", "id": p["id"], "call": p["call"], "t0": t})
        p["rgb"][y * BLOCK:(y + 1) * BLOCK, x * BLOCK:(x + 1) * BLOCK] = rgb
        p["have"][y, x] = True
        p["mode"], p["sc"] = ev.get("mode", ""), ev["sc"]
        out.append({"kind": "block", "id": p["id"], "x": x, "y": y, "rgb": rgb, "call": p["call"],
                    "blocks": int(p["have"].sum()), "mode": p["mode"]})
        return out


__all__ = ["Receiver", "Pictures", "transmission_bits", "picture_frames", "preamble_bits", "block_data", "frame_bits", "modulate", "encode_block", "decode_block",
           "decode_mcu", "encode_mcu", "render_mcu", "crc16", "viterbi", "conv_encode", "pack_info", "unpack_info",
           "text_of", "BAUD", "CENTRE_HZ", "SCALES", "WIDTH", "HEIGHT", "MAX_DATA_BITS"]
