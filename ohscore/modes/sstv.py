"""SSTV transmit: a VIS header and the picture's lines for Robot 36, Martin
M1, Scottie S1 and PD120 (the modes actually seen on QO-100 NB, per
DESIGN.md), the PNG writer the apps' pictures share, and the timing tables
both were built from.

Receive is shack_sdr's Rust `sstv` decoder since Radio's SDR milestone 2
(modes/sdrmode.py SstvDecoder), in fourteen modes. The Python decoder that
lived here was removed once its pictures on 116 synthetic fixtures were
captured as the golden numbers the Rust one must never fall below (ohs-libs
shack_sdr testdata/sstv/golden.json, from this module at 3fcfbcc); its
notes on finding the VIS header by tone detectors, tracking each line's
sync and starting a picture from line syncs alone went into the Rust
decoder's own comments (src/sstv/mod.rs). The encoder stays: transmit is
unchanged, and the tests decode what it sends with the Rust decoder.

Every timing constant in MODES (VIS codes, sync/porch/separator/scan
durations, colour order, resolutions) and the Y/R-Y/B-Y conversion in
_rgb_to_yryby is transcribed from JL Barber (N7CXI),
"Proposal for SSTV Mode Specifications", Dayton SSTV forum, 20 May 2000
-- see the comment above MODES for the specific section cited for each
mode. An earlier revision of this module had Scottie S1 and PD120 timed
from memory with no encoder to check them against, and separately had
the VIS header's own data-bit frequency convention backwards (1=1300Hz
rather than the paper's 1=1100Hz) -- invisible in this module's own
loopback tests either way, since encoder and decoder only had to agree
with each other, but wrong for talking to a real transmitter/receiver.
Fetching the actual paper and re-deriving every constant from it, rather
than continuing to trust memory, is what caught both.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

FS = 12_000.0

# --- per-mode timing tables -------------------------------------------------
# All times in milliseconds. Every constant below (VIS code, resolution,
# sync/porch/separator timings, scan order) is transcribed from JL Barber
# (N7CXI), "Proposal for SSTV Mode Specifications", presented at the
# Dayton SSTV forum, 20 May 2000 -- the paper's own data sources are the
# Robot 1200C firmware for Scottie/Martin/Robot, and the PD modes' authors
# directly (Don Rotier/Paul Turner) for PD. Fetched as a PDF and extracted
# with pdftotext; page references below are to that extracted text, not
# the PDF's own page numbers (it has none).
#
# Robot36 ("ROBOT 36 COLOR" section): sync(9ms@1200) + porch(3ms@1500) +
# Y scan(88ms) + an "Even"(1500Hz)/"Odd"(2300Hz) separator(4.5ms) that
# itself identifies which chroma channel follows + a fixed 1900Hz
# porch(1.5ms) + the chroma scan(44ms) -- R-Y on even lines, B-Y on odd.
# An earlier revision of this module omitted that 1.5ms/1900Hz porch
# entirely (going straight from the separator into the chroma scan),
# which cost exactly 1.5ms = 18 samples of alignment on every line's
# ~44ms/320px (1.65 samples/pixel) chroma scan -- enough to corrupt
# roughly a tenth of each chroma scan's pixels.
#
# Martin M1 ("MARTIN MODES" section): sync(4.862ms@1200) + porch
# (0.572ms@1500) + G + sep(0.572@1500) + B + sep(0.572@1500) + R + a
# *fourth* sep(0.572@1500) before the next line's sync -- "Repeat the
# above sequence for 256 lines" includes that trailing separator as step
# 8, which an earlier revision omitted (3 separators, not 4), 0.572ms
# short of the spec's own total line time (446.446ms = 114.3s/256).
#
# Scottie S1 ("SCOTTIE MODES" section) is the one with real structural
# surprises, both noted explicitly in the paper: the *first* scan line
# only gets an extra "starting" sync pulse (9ms@1200) before its leading
# separator, and the regular sync pulse sits between the Blue and Red
# scans (with its own 1.5ms@1500 porch before Red), not at the line
# break the way every other mode here puts it. An earlier revision
# treated every line identically and omitted that porch before Red.
#
# PD120 ("PD Modes" section) was already correct in an earlier revision:
# sync(20ms@1200) + porch(2.08ms@1500) + Y(odd line) + R-Y(averaged) +
# B-Y(averaged) + Y(even line), 121.600ms each, covering two output rows
# per iteration (4:2:0-style chroma, shared across the pair).
MODES = {
    "robot36": {"vis": 8, "width": 320, "height": 240, "kind": "robot",
                "sync_ms": 9.0, "porch_ms": 3.0, "y_ms": 88.0,
                "chroma_sep_ms": 4.5, "chroma_porch_ms": 1.5, "chroma_porch_hz": 1900.0, "chroma_ms": 44.0},
    "martinm1": {"vis": 44, "width": 320, "height": 256, "kind": "martin",
                 "sync_ms": 4.862, "porch_ms": 0.572, "scan_ms": 146.432, "sep_ms": 0.572,
                 "order": "gbr"},
    "scottie_s1": {"vis": 60, "width": 320, "height": 256, "kind": "scottie",
                   "start_sync_ms": 9.0, "sep_ms": 1.5, "scan_ms": 138.240,
                   "sync_ms": 9.0, "porch_ms": 1.5, "order": "gbr"},
    "pd120": {"vis": 95, "width": 640, "height": 496, "kind": "pd",
              "sync_ms": 20.0, "porch_ms": 2.08, "scan_ms": 121.6},
}
VIS_TO_MODE = {m["vis"]: name for name, m in MODES.items()}


# --- VIS header -------------------------------------------------------------

def _vis_bits(mode_id: int) -> str:
    """7 data bits (LSB first) + even parity. Per the Dayton paper's
    calibration-header table (JL Barber, "Proposal for SSTV Mode
    Specifications", 20 May 2000, p.2): "bit 0  1100hz = '1', 1300hz =
    '0'" and "PARITY  Even=1300hz, Odd=1100hz" -- i.e. 1 is the *lower*
    tone, 0 the higher, for both data and parity bits alike. An earlier
    revision of this module had this backwards (1=1300, 0=1100), which
    would have been invisible in this module's own loopback tests (its
    encoder and decoder agreed with each other) but unable to signal a
    correct VIS code to a real receiver."""
    bits = [(mode_id >> i) & 1 for i in range(7)]
    parity = sum(bits) % 2
    return "".join(str(b) for b in bits) + str(parity)


def _vis_bit_freq(bit: str) -> float:
    return 1100.0 if bit == "1" else 1300.0


def _vis_segments(mode_id: int) -> list[tuple[float, object]]:
    """(ms, Hz) for the whole VIS header: double leader, break, start bit,
    7 data bits, parity, stop bit. Timings from the Dayton paper's
    calibration-header table (see _vis_bits)."""
    segs = [(300.0, 1900.0), (10.0, 1200.0), (300.0, 1900.0), (30.0, 1200.0)]
    segs += [(30.0, _vis_bit_freq(b)) for b in _vis_bits(mode_id)]
    segs.append((30.0, 1200.0))
    return segs


# --- tone synthesis (shared by the VIS header and every mode's image data) -
#
# An SSTV picture is really just a very long FSK transmission whose
# "symbols" happen to be pixel brightnesses instead of data bits, so one
# code path builds both the VIS header and the image scans: a list of
# (milliseconds, payload) segments, the payload either a tone in Hz or a
# row of pixel values to scan across the segment, turned into one
# per-sample frequency array and synthesised by one phase integration.
#
# Segment edges are placed at round(cumulative time * FS), never by rounding
# each segment's own length and adding those up. The earlier encoder did the
# latter, and since most of these durations are not whole samples (Martin's
# 146.432 ms scan is 1757.18 samples; PD120's 121.6 ms is 1459.2) the line
# period came out up to 0.8 samples short of the specification every line:
# a clock error of up to 520 ppm (PD120), which slants the picture on any
# receiver that keeps to the specification -- 82 pixels across by PD120's
# last line. Placed cumulatively, the error never exceeds half a sample.

def _px_to_hz(v: np.ndarray) -> np.ndarray:
    return 1500.0 + np.clip(v, 0, 255).astype(np.float64) / 255.0 * 800.0


def _segments_to_freq(segs: list[tuple[float, object]]) -> np.ndarray:
    ms = np.array([s[0] for s in segs], dtype=np.float64)
    edges = np.round(np.concatenate([[0.0], np.cumsum(ms)]) * FS / 1000.0).astype(int)
    out = np.empty(edges[-1], dtype=np.float64)
    for (_, payload), a, b in zip(segs, edges[:-1], edges[1:]):
        if np.isscalar(payload):
            out[a:b] = payload
        else:
            # Pixel i covers the i-th w-th of the segment, nearest-neighbour,
            # vectorised -- no per-pixel Python loop.
            w, n = len(payload), b - a
            idx = (np.arange(n) * w // max(n, 1)).clip(0, w - 1)
            out[a:b] = _px_to_hz(payload)[idx]
    return out


def _synthesize(freq_trace: np.ndarray) -> np.ndarray:
    phase = 2 * np.pi * np.cumsum(freq_trace) / FS
    return np.sin(phase).astype(np.float32)


class Encoder:
    """render(image=<HxWx3 uint8 numpy array>, mode="robot36"|"martinm1"|
    "scottie_s1"|"pd120"). All four modes DESIGN.md names are implemented,
    so the decoder has this module's own encoder to loop back against for
    every one of them, not just two."""

    def render(self, image: np.ndarray, mode: str = "robot36", **_opts) -> np.ndarray:
        spec = MODES[mode]
        img = _fit_image(image, spec["width"], spec["height"])
        segs = _vis_segments(spec["vis"])
        builder = {"robot": self._robot_lines, "martin": self._martin_lines,
                   "scottie": self._scottie_lines, "pd": self._pd_lines}[spec["kind"]]
        segs += builder(img, spec)
        return _synthesize(_segments_to_freq(segs))

    def _robot_lines(self, img, spec):
        segs = []
        yryby = _rgb_to_yryby(img)
        for y in range(spec["height"]):
            even = (y % 2 == 0)
            segs.append((spec["sync_ms"], 1200.0))
            segs.append((spec["porch_ms"], 1500.0))
            segs.append((spec["y_ms"], yryby[y, :, 0]))
            # "Even" separator (1500 Hz) carries R-Y, "Odd" (2300 Hz) carries
            # B-Y -- the paper's own wording, not a free choice; channel
            # index 1 is R-Y, 2 is B-Y (see _rgb_to_yryby).
            segs.append((spec["chroma_sep_ms"], 1500.0 if even else 2300.0))
            segs.append((spec["chroma_porch_ms"], spec["chroma_porch_hz"]))
            segs.append((spec["chroma_ms"], yryby[y, :, 1] if even else yryby[y, :, 2]))
        return segs

    def _martin_lines(self, img, spec):
        segs = []
        for y in range(spec["height"]):
            row = img[y]
            channels = {"r": row[:, 0], "g": row[:, 1], "b": row[:, 2]}
            segs.append((spec["sync_ms"], 1200.0))
            segs.append((spec["porch_ms"], 1500.0))
            for ch in spec["order"]:
                segs.append((spec["scan_ms"], channels[ch]))
                segs.append((spec["sep_ms"], 1500.0))   # one after every channel, including the last
        return segs

    def _scottie_lines(self, img, spec):
        segs = []
        order = spec["order"]
        for y in range(spec["height"]):
            row = img[y]
            channels = {"r": row[:, 0], "g": row[:, 1], "b": row[:, 2]}
            if y == 0:
                # The out-of-sequence "starting" sync -- first line only.
                segs.append((spec["start_sync_ms"], 1200.0))
            segs.append((spec["sep_ms"], 1500.0))
            segs.append((spec["scan_ms"], channels[order[0]]))   # G
            segs.append((spec["sep_ms"], 1500.0))
            segs.append((spec["scan_ms"], channels[order[1]]))   # B
            segs.append((spec["sync_ms"], 1200.0))               # the "regular" sync, between B and R
            segs.append((spec["porch_ms"], 1500.0))
            segs.append((spec["scan_ms"], channels[order[2]]))   # R
        return segs

    def _pd_lines(self, img, spec):
        segs = []
        yryby = _rgb_to_yryby(img)
        h = spec["height"]
        for y in range(0, h, 2):
            y2 = min(y + 1, h - 1)
            # R-Y/B-Y are each "averaged for two lines" per the paper --
            # the average of the two rows' own chroma, not recomputed from
            # an averaged RGB, matching how a real encoder with only one
            # chroma scan's worth of time to spend would do it.
            ry = (yryby[y, :, 1].astype(np.float64) + yryby[y2, :, 1]) / 2
            by = (yryby[y, :, 2].astype(np.float64) + yryby[y2, :, 2]) / 2
            segs.append((spec["sync_ms"], 1200.0))
            segs.append((spec["porch_ms"], 1500.0))
            segs.append((spec["scan_ms"], yryby[y, :, 0]))
            segs.append((spec["scan_ms"], ry))
            segs.append((spec["scan_ms"], by))
            segs.append((spec["scan_ms"], yryby[y2, :, 0]))
        return segs


def _fit_image(image: np.ndarray, w: int, h: int) -> np.ndarray:
    img = np.asarray(image)
    if img.shape[0] == h and img.shape[1] == w:
        return img.astype(np.uint8)
    # Nearest-neighbour resize -- no scipy/PIL available, and a test image
    # being gridded slightly differently than the mode's native size is not
    # worth a real interpolator for.
    ys = (np.arange(h) * img.shape[0] / h).astype(int).clip(0, img.shape[0] - 1)
    xs = (np.arange(w) * img.shape[1] / w).astype(int).clip(0, img.shape[1] - 1)
    return img[np.ix_(ys, xs)].astype(np.uint8)


def _rgb_to_yryby(img: np.ndarray) -> np.ndarray:
    """RGB -> [Y, R-Y, B-Y], scaled 0-255, exactly as given in the Dayton
    paper's Appendix B (its own note: "compliant with ITU BT.Rec 601 (the
    1953 NTSC standard)" -- this is SSTV's own specific scaling, not a
    generic YCbCr, and Robot36/PD120 are explicit about using it)."""
    img = img.astype(np.float64)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    y = 16.0 + 0.003906 * (65.738 * r + 129.057 * g + 25.064 * b)
    ry = 128.0 + 0.003906 * (112.439 * r - 94.154 * g - 18.285 * b)
    by = 128.0 + 0.003906 * (-37.945 * r - 74.494 * g + 112.439 * b)
    return np.clip(np.stack([y, ry, by], axis=-1), 0, 255).astype(np.uint8)


# --- PNG writer (pure python: struct + zlib, no external assets or Pillow) -

def _write_png(path, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    raw = bytearray()
    for row in rgb:
        raw.append(0)  # filter type "None" per scanline
        raw += row.astype(np.uint8).tobytes()
    idat = chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    iend = chunk(b"IEND", b"")
    Path(path).write_bytes(sig + ihdr + idat + iend)
