"""SSTV: VIS header detection, line decode for Robot 36, Martin M1, Scottie
S1 and PD120 (the modes actually seen on QO-100 NB, per DESIGN.md), and an
encoder for all four, so the decoder is tested against a known-good image
for every mode rather than against recordings for some of them.

Every timing constant in MODES (VIS codes, sync/porch/separator/scan
durations, colour order, resolutions) and the Y/R-Y/B-Y conversion in
_rgb_to_yryby/_yryby_to_rgb is transcribed from JL Barber (N7CXI),
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

The general SSTV picture -- a VIS header, then per line a sync pulse,
a porch, and one or more channel scans mapping 1500-2300 Hz to 0-255 --
was already right; only the per-mode details needed the source.

Decoding instantaneous frequency without scipy: each incoming block is
quadrature-mixed down from a fixed reference tone and low-pass filtered
(a short FIR, state carried between blocks so there's no discontinuity at
block boundaries) -- the phase derivative of that baseband *is* the
instantaneous frequency. This is deliberately not a Hilbert transform over
the whole image-so-far: SSTV images run tens of seconds to a couple of
minutes, and re-transforming an ever-growing buffer on every feed() call
would be O(n^2) over the image -- exactly what DESIGN.md's "keep up in
real time on a Pi 400" rules out. Each block costs the same regardless of
how much of the image has already arrived.
"""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path
from typing import Callable

import numpy as np

FS = 12_000.0
REF_HZ = 1900.0  # demod reference: centred on the VIS leader, within the FIR's passband of every SSTV tone used (1100-2300 Hz)

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


VIS_MS = 300 + 10 + 300 + 30 + 8 * 30 + 30   # leader start to the end of the stop bit


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


def _yryby_to_rgb(y, ry, by) -> np.ndarray:
    """Inverse of _rgb_to_yryby, per the same Appendix B."""
    y = y.astype(np.float64) - 16.0
    ry = ry.astype(np.float64) - 128.0
    by = by.astype(np.float64) - 128.0
    r = 0.003906 * (298.082 * y + 408.583 * ry)
    g = 0.003906 * (298.082 * y - 100.291 * by - 208.120 * ry)
    b = 0.003906 * (298.082 * y + 516.411 * by)
    return np.clip(np.stack([r, g, b], axis=-1), 0, 255).astype(np.uint8)


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


# --- frequency demodulation --------------------------------------------------

class _FreqDemod:
    """Quadrature demod against REF_HZ with a short FIR lowpass, state
    carried between blocks so there's no seam at block boundaries and no
    re-processing of audio already consumed -- see the module docstring.

    A symmetric FIR is a (TAPS-1)/2-sample *delay*: its output at sample n
    describes the input at n-GD. The stream this returns is advanced by
    that much -- its first GD samples (which describe time before the
    first input) are dropped -- so output sample k describes input sample
    k, and the stream runs GD samples behind the input it has been given.
    An earlier revision instead *prepended* GD samples to "align" it, which
    doubled the delay: every pixel was read 14 samples (1.2 ms) late, four
    pixels across in Robot36 and six in PD120, measured with a frequency
    step at a known sample."""

    # SSTV's pixel rate is far higher than its tone range would suggest: Robot
    # 36's Y scan is 320 px in 88 ms, 3.3 samples/pixel at 12 kHz, and PD120's
    # is nearer 2.3. A filter long enough to matter for noise rejection (tens
    # of taps) is then longer than *several pixels*, not just the short sync/
    # porch segments -- it doesn't merely delay the signal, it blurs adjacent
    # pixels into each other. This has to be fast, at the cost of being noisy;
    # the pixel averaging in Decoder._pixels does the rest of the smoothing.
    TAPS = 15

    def __init__(self):
        cutoff = 1400.0 / (FS / 2)  # passes the whole 1100-2300 Hz tone range once shifted to baseband
        n = np.arange(self.TAPS) - (self.TAPS - 1) / 2
        h = np.sinc(cutoff * n) * cutoff
        h *= np.hamming(self.TAPS)
        self._kernel = (h / h.sum()).astype(np.complex128)
        self._hist = np.zeros(self.TAPS - 1, dtype=np.complex128)
        self._n_total = 0  # samples of audio mixed so far, for NCO phase continuity
        self._prev_phase = None  # last baseband phase emitted, for continuity of the frequency derivative
        self._to_drop = (self.TAPS - 1) // 2

    def process(self, audio: np.ndarray) -> np.ndarray:
        n = np.arange(self._n_total, self._n_total + len(audio))
        self._n_total += len(audio)
        mixed = audio.astype(np.complex128) * np.exp(-2j * np.pi * REF_HZ * n / FS)
        extended = np.concatenate([self._hist, mixed])
        self._hist = extended[-(self.TAPS - 1):]
        baseband = np.convolve(extended, self._kernel, mode="valid")
        phase = np.unwrap(np.angle(baseband))
        if self._prev_phase is not None and len(phase):
            # Continue the unwrapped phase across the block edge, so the first
            # sample's derivative is real rather than assumed to be REF_HZ.
            d0 = (phase[0] - self._prev_phase + np.pi) % (2 * np.pi) - np.pi
            phase = phase - phase[0] + self._prev_phase + d0
            inst = np.diff(np.concatenate([[self._prev_phase], phase]))
        else:
            inst = np.concatenate([[0.0], np.diff(phase)])
        if len(phase):
            self._prev_phase = phase[-1]
        out = REF_HZ + inst * FS / (2 * np.pi)
        if self._to_drop:
            k = min(self._to_drop, len(out))
            out = out[k:]
            self._to_drop -= k
        return out


# --- tone detection ------------------------------------------------------------

def _tone_ratio(x: np.ndarray, f: float, n: int) -> np.ndarray:
    """For every window x[i:i+n], the fraction of its power that is a tone
    at f Hz: 1.0 for a pure tone at f filling the window, near 0 for a
    tone elsewhere or for noise. A quadrature mix and a boxcar of n samples,
    i.e. a filter matched to an n-sample burst of f -- so its peak over i is
    where such a burst starts, to a sample, and the boxcar's nulls at
    multiples of FS/n put every tone that many hertz away at exactly zero
    (10 ms windows: the VIS tones 1100/1200/1300/1900 are mutually
    invisible). Normalising by the window's own power makes it level-blind,
    so one threshold serves a strong signal and a weak one."""
    if len(x) < n:
        return np.zeros(0)
    m = np.arange(len(x))
    c = np.concatenate([[0j], np.cumsum(x * np.exp(-2j * np.pi * f * m / FS))])
    p = np.concatenate([[0.0], np.cumsum(x * x)])
    amp = (c[n:] - c[:-n]) / n
    pw = (p[n:] - p[:-n]) / n
    return 2.0 * np.abs(amp) ** 2 / (pw + 1e-12)


# --- line layouts --------------------------------------------------------------

def _layout(spec: dict) -> dict:
    """Where everything sits in one line, in ms from the line's start, from
    MODES' timings: the line period, where its sync pulse is, and each scan
    as (channel, offset, duration). Computed exactly (not per-segment
    rounded), so a decoder that keeps to it keeps to the specification."""
    k = spec["kind"]
    out = {"head": 0.0, "sync": spec["sync_ms"], "sync_off": 0.0, "sep": None}
    if k == "robot":
        y0 = spec["sync_ms"] + spec["porch_ms"]
        sep0 = y0 + spec["y_ms"]
        c0 = sep0 + spec["chroma_sep_ms"] + spec["chroma_porch_ms"]
        out.update(line=c0 + spec["chroma_ms"], scans=[("y", y0, spec["y_ms"]), ("c", c0, spec["chroma_ms"])],
                   sep=(sep0, spec["chroma_sep_ms"]))
    elif k == "martin":
        t, scans = spec["sync_ms"] + spec["porch_ms"], []
        for ch in spec["order"]:
            scans.append((ch, t, spec["scan_ms"]))
            t += spec["scan_ms"] + spec["sep_ms"]
        out.update(line=t, scans=scans)
    elif k == "scottie":
        o, s = spec["order"], spec["scan_ms"]
        g0 = spec["sep_ms"]
        b0 = g0 + s + spec["sep_ms"]
        sync0 = b0 + s
        r0 = sync0 + spec["sync_ms"] + spec["porch_ms"]
        # Line 0 is preceded by the extra "starting" sync; every line's own
        # sync sits between B and R, so that is the one tracked.
        out.update(line=r0 + s, scans=[(o[0], g0, s), (o[1], b0, s), (o[2], r0, s)],
                   sync_off=sync0, head=spec["start_sync_ms"])
    else:  # pd
        t, s = spec["sync_ms"] + spec["porch_ms"], spec["scan_ms"]
        out.update(line=t + 4 * s, scans=[("y1", t, s), ("ry", t + s, s), ("by", t + 2 * s, s), ("y2", t + 3 * s, s)])
    return out


def _ms_n(ms: float) -> int:
    return int(round(ms / 1000.0 * FS))


def _ms_f(ms: float) -> float:
    return ms / 1000.0 * FS


class Decoder:
    """SSTV receive. feed() demodulates to instantaneous frequency and hands
    the result to a small state machine: idle (looking for a VIS header,
    or a train of line syncs) or mid-image (one line at a time). Images are written
    as PNG into `out_dir`; `emit` gets start/line/done events, with each
    line's pixels included (base64) so a console can paint the picture as
    it arrives rather than only once it's finished.

    Timing is closed-loop, the way every working SSTV receiver does it:

    - The VIS header is found with tone detectors (_tone_ratio) rather than
      by thresholding the instantaneous frequency, and placed by the peak of
      a template match -- leaders, break and start bit -- whose edges pin it
      to a sample or two. Each data bit is judged 1100 against 1300 Hz over
      its middle 25 ms only, and the parity bit is checked.
    - Each line's sync pulse is then *found*, within a few milliseconds of
      where it is expected, by the 1200 Hz detector matched to its length,
      and a second-order tracking loop (line start and line period) follows
      it -- which also follows a transmitting sound card whose clock is not
      exactly 12 kHz.
    - With no VIS header heard - tuned in, or the radio started, part way
      through a picture - a picture is still started from its line syncs
      alone, as QSSTV and OpenWebRX+ do (_seek_sync): a run of 1200 Hz
      pulses at one mode's sync length and line period names the mode and
      places the line. Up to 0.1.10 only a VIS header started a picture,
      so on Brian's controller a Scottie picture joined half way through
      was on the waterfall for half a minute and never decoded at all.
      Such a picture is marked "partial" (its first line is wherever we
      came in, not the top) and ends when its syncs stop, since where its
      last line falls is not known.

    The earlier decoder did neither. It slid a 300 ms window over the
    frequency trace in 37.5 ms steps and took the first window that looked
    steady, so where it believed the header ended was quantised to 37.5 ms;
    then it cut every line at the nominal durations from there, open loop,
    never looking at a sync pulse again. Whatever the VIS error was, every
    line had it: a picture shifted sideways by 25-80 px, the sync pulse
    (1200 Hz, read as black in every channel, which Y/R-Y/B-Y turns green)
    showing as a band down one side. And its steadiness test -- the 90th
    percentile of frequency deviation under 120 Hz -- was a test of the
    noise, not of the tone: at sigma 0.05 the 15-tap discriminator's spikes
    alone fail it, so no header was found at all."""

    VIS_MIN = 0.5      # template score (mean tone fraction) to believe a VIS header
    SYNC_MIN = 0.4     # tone fraction to believe a sync pulse was found
    SYNC_SEARCH_MS = 8.0
    LOOP_PHASE = 0.5   # tracking loop: share of a measured sync error applied to this line
    LOOP_FREQ = 0.05   # ... and to the line period
    # Starting from line syncs (_seek_sync): at least this many lines, and
    # this much audio, of pulses before a picture is believed - 1.5 s is
    # ten Robot 36 lines, three of PD120's; a few noise spikes cannot line
    # up that many times at one mode's exact period.
    TRAIN_LINES = 5
    TRAIN_S = 1.5
    TRAIN_MIN = 0.6    # mean tone fraction at the pulses
    TRAIN_MISS = 1     # pulses in the train allowed to be missing (a fade, a click)
    # The detector's window: no longer than 9 ms, so a 20 ms PD sync is
    # still seen with the dial 30 Hz out (a window matched to all of it
    # nulls a tone 1/20 ms = 50 Hz away, and loses half at 30 Hz).
    TRAIN_WIN_MS = 9.0
    PARTIAL_LOST = 4   # a partial picture ends after this many lines in a row without a sync

    def __init__(self, emit: Callable[[dict], None], out_dir: str = ".", **_opts):
        self.emit = emit
        self.out_dir = Path(out_dir)
        self.reset()

    def reset(self) -> None:
        self._demod = _FreqDemod()
        self._audio = np.zeros(0, dtype=np.float64)
        self._freq = np.zeros(0, dtype=np.float64)
        self._base = 0              # absolute sample index of _audio[0] and _freq[0]
        self._state = "idle"        # idle | imaging
        self._mode = None
        self._spec = None
        self._rows: list = []
        self._line = 0
        self._n_images = 0
        self._partial = False       # started from line syncs, not a VIS header
        self._misses = 0            # lines in a row without a sync found (partial pictures)
        self._sync_seen = 0         # absolute sample up to which _seek_sync last looked

    def feed(self, audio: np.ndarray, t: float) -> None:
        x = np.asarray(audio, dtype=np.float64)
        self._audio = np.concatenate([self._audio, x])
        self._freq = np.concatenate([self._freq, self._demod.process(x)])
        if self._state == "idle" and not self._seek_vis():
            self._seek_sync()
        while self._state == "imaging" and self._decode_line():
            pass

    def _drop_to(self, abs_idx: int) -> None:
        k = int(abs_idx) - self._base
        if k > 0:
            self._audio = self._audio[k:]
            self._freq = self._freq[k:]
            self._base += k

    # -- VIS ------------------------------------------------------------------
    def _seek_vis(self) -> bool:
        """Look for a VIS header; start the picture it names. True while
        a header may still be arriving, or once one has started a picture
        - either way the line-sync search must wait."""
        n = _ms_n(10)
        lead, brk, startbit, bit = _ms_n(300), _ms_n(10), _ms_n(30), _ms_n(30)
        H = _ms_n(VIS_MS)
        settle = _ms_n(20)           # see a little past the best candidate before believing it
        a = self._audio
        last = len(a) - H - settle   # last candidate start whose whole header is here
        if last < 0:
            return False
        r = {f: _tone_ratio(a, f, n) for f in (1100.0, 1200.0, 1300.0, 1900.0)}
        C = {f: np.concatenate([[0.0], np.cumsum(v)]) for f, v in r.items()}
        T = np.arange(last + settle + 1)

        def seg(f, s, e):
            # mean tone fraction over the windows lying wholly inside [t0+s, t0+e)
            lo, hi = T + s, T + e - n + 1
            return (C[f][hi] - C[f][lo]) / (hi - lo)

        score = (seg(1900.0, 0, lead) + seg(1200.0, lead, lead + brk)
                 + seg(1900.0, lead + brk, 2 * lead + brk)
                 + seg(1200.0, 2 * lead + brk, 2 * lead + brk + startbit)) / 4
        best = int(np.argmax(score))
        if score[best] < self.VIS_MIN or best > last:
            # Nothing (or a header still arriving): keep only what could
            # still be the start of one - and enough for _seek_sync to
            # look for a train of line syncs in.
            if score[best] < self.VIS_MIN:
                self._drop_to(self._base + max(0, len(a) - max(H + settle, self._train_keep())))
                return False
            return True
        b0 = best + 2 * lead + brk + startbit
        bits = []
        guard = _ms_n(2.5)
        for k in range(8):
            s, e = b0 + k * bit + guard, b0 + (k + 1) * bit - guard
            bits.append(1 if r[1100.0][s:e - n + 1].mean() > r[1300.0][s:e - n + 1].mean() else 0)
        mode_id = sum(b << i for i, b in enumerate(bits[:7]))
        mode = VIS_TO_MODE.get(mode_id)
        if sum(bits) % 2 or mode is None:
            # Bad parity or a mode we do not decode: step past this header.
            self._drop_to(self._base + best + H)
            return False
        self._begin(mode, float(self._base + best + H) + _ms_f(_layout(MODES[mode])["head"]), partial=False)
        return True

    def _begin(self, mode: str, start: float, partial: bool) -> None:
        """Start a picture in `mode` whose first line begins at absolute
        sample `start`."""
        self._mode, self._spec = mode, MODES[mode]
        self._lay = _layout(self._spec)
        self._rows = []
        self._line = 0
        self._n_images += 1
        self._name = f"sstv_{mode}_{self._n_images:04d}.png"
        self._start = start
        self._period = _ms_f(self._lay["line"])
        self._first = True
        self._partial = partial
        self._misses = 0
        ev = {"mode": "sstv", "state": "start", "name": self._name,
              "fmt": mode, "width": self._spec["width"], "height": self._spec["height"]}
        if partial:
            ev["partial"] = True
        self.emit(ev)
        self._state = "imaging"

    # -- line syncs, for a picture whose VIS header we did not hear ----------
    def _train_lines(self, period_n: float) -> int:
        return max(self.TRAIN_LINES, int(np.ceil(self.TRAIN_S * FS / period_n)))

    def _train_keep(self) -> int:
        """Audio to keep while idle: the longest train any mode needs, and
        a line more so the train's first line is whole."""
        return max(int(np.ceil((self._train_lines(p) + 1) * p))
                   for p in (_ms_f(_layout(m)["line"]) for m in MODES.values()))

    def _seek_sync(self) -> None:
        """Start a partial picture if the audio idle has kept ends in a run
        of line syncs: 1200 Hz pulses of one mode's sync length, one line
        period apart, TRAIN_LINES or more of them. Every mode is scored
        and the best taken; the modes' periods (150 ms to 508 ms) are far
        enough apart that a train at one fails the others."""
        a = self._audio
        end = self._base + len(a)
        if end - self._sync_seen < _ms_n(250):     # a look every quarter second is plenty
            return
        self._sync_seen = end
        ratios: dict[int, np.ndarray] = {}
        best = None
        for mode, spec in MODES.items():
            lay = _layout(spec)
            P = _ms_f(lay["line"])
            K = self._train_lines(P)
            sync_n = _ms_n(lay["sync"])
            n = min(sync_n, _ms_n(self.TRAIN_WIN_MS))
            if n not in ratios:
                ratios[n] = _tone_ratio(a, 1200.0, n)
            r = ratios[n]
            base0 = len(r) - (K - 1) * P - int(np.ceil(P))   # the first pulse lies in [base0, base0 + P)
            if base0 < 0:
                continue
            phi = np.arange(int(np.ceil(P)))
            idx = np.rint(base0 + phi[:, None] + P * np.arange(K)[None, :]).astype(int).clip(0, len(r) - 1)
            at = r[idx]
            # Half a line from every pulse is picture (1500-2300 Hz), never
            # 1200 Hz: a train must be pulses, not a steady 1200 Hz carrier
            # or a tuning tone, which would otherwise pass for every mode.
            gap = r[np.rint(idx + P / 2).astype(int).clip(0, len(r) - 1)].mean(axis=1)
            ok = ((at < self.SYNC_MIN).sum(axis=1) <= self.TRAIN_MISS) & (gap < self.SYNC_MIN / 2)
            score = np.where(ok, at.mean(axis=1), 0.0)
            k = int(np.argmax(score))
            if score[k] < self.TRAIN_MIN or (best is not None and score[k] <= best[0]):
                continue
            # A window shorter than the pulse scores alike all along it:
            # take the middle of that plateau, less half the difference, as
            # the pulse's start. The first line's sync search then places it
            # to a sample (gain 1 on the first line, as after a VIS header).
            hi = score[k] * 0.9
            lo_k, hi_k = k, k
            while lo_k > 0 and score[lo_k - 1] >= hi:
                lo_k -= 1
            while hi_k < len(score) - 1 and score[hi_k + 1] >= hi:
                hi_k += 1
            pulse = base0 + (lo_k + hi_k) / 2 - (sync_n - n) / 2
            best = (score[k], mode, pulse - _ms_f(lay["sync_off"]))
        if best is None:
            return
        _score, mode, start = best
        # The first whole line in the buffer: the decoder needs its sync
        # search window before the pulse.
        P = _ms_f(_layout(MODES[mode])["line"])
        while start + _ms_f(_layout(MODES[mode])["sync_off"]) - _ms_n(self.SYNC_SEARCH_MS) < 0:
            start += P
        self._begin(mode, self._base + start, partial=True)
        while self._decode_line():
            pass

    # -- lines ----------------------------------------------------------------
    def _decode_line(self) -> bool:
        lay, spec = self._lay, self._spec
        sync_n = _ms_n(lay["sync"])
        W = _ms_n(self.SYNC_SEARCH_MS)
        pred = self._start
        sync_at = int(round(pred + _ms_f(lay["sync_off"])))
        # Enough audio for the sync search and (less a couple of ms, so the
        # last line of a transmission that simply stops still completes)
        # the whole line.
        need = max(sync_at + W + sync_n, int(pred + self._period) - _ms_n(2))
        if need > self._base + len(self._freq):
            return False

        seg = self._audio[sync_at - W - self._base:sync_at + W + sync_n - self._base]
        r = _tone_ratio(seg, 1200.0, sync_n)
        start = pred
        # Line 0's sync follows the VIS stop bit with no gap in most modes:
        # 30 ms of 1200 Hz then the sync's own, one plateau a matched
        # detector cannot place a pulse in (it found the stop bit, and the
        # first line read the sync as picture). The header's own template
        # fit is sample-accurate, so line 0 keeps to it.
        abuts = self._line == 0 and lay["sync_off"] == 0 and lay["head"] == 0 and not self._partial
        found = False
        if len(r) and not abuts:
            k = int(np.argmax(r))
            if r[k] >= self.SYNC_MIN:
                found = True
                frac = 0.0
                if 0 < k < len(r) - 1:
                    den = r[k - 1] - 2 * r[k] + r[k + 1]
                    frac = 0.5 * (r[k - 1] - r[k + 1]) / den if den < 0 else 0.0
                err = (k + frac - W)
                # The header gives the first line's position to a millisecond
                # or so; the first sync found is better, so take all of it.
                gain = 1.0 if self._first else self.LOOP_PHASE
                start = pred + gain * err
                if not self._first:
                    self._period += self.LOOP_FREQ * err
                self._first = False

        chans = {ch: self._pixels(start + _ms_f(off), _ms_f(dur), spec["width"])
                 for ch, off, dur in lay["scans"]}
        k = spec["kind"]
        if k == "robot":
            # The separator says which chroma this line carries (1500 Hz
            # "even" = R-Y, 2300 Hz "odd" = B-Y), so a line lost to noise
            # cannot swap the colours of every line after it.
            s0, sd = lay["sep"]
            sep_hz = float(np.mean(self._pixels(start + _ms_f(s0 + sd / 4), _ms_f(sd / 2), 1, raw=True)))
            is_ry = sep_hz < 1900.0
            prev = self._rows[-1] if self._rows else (None, chans["c"], chans["c"])
            ry = chans["c"] if is_ry else prev[1]
            by = chans["c"] if not is_ry else prev[2]
            self._rows.append((chans["y"], ry, by))
            self._emit_line(_yryby_to_rgb(chans["y"], ry, by))
        elif k == "pd":
            for y in ("y1", "y2"):
                row = _yryby_to_rgb(chans[y], chans["ry"], chans["by"])
                self._rows.append(row)
                self._emit_line(row)
        else:
            row = np.stack([chans["r"], chans["g"], chans["b"]], axis=-1)
            self._rows.append(row)
            self._emit_line(row)

        self._start = start + self._period
        self._line += 1
        self._drop_to(int(self._start) - 4 * W - _ms_n(lay["line"]) // 4)
        if self._partial:
            # Where a picture joined part way through ends is not known
            # (its first line was not the top), so it ends when its syncs
            # stop, without the lines read since the last one found. "Stop"
            # is judged with _seek_sync's short window, which still sees a
            # PD sync with the dial 30 Hz out; the matched window above,
            # which places the pulse, does not, and with it alone a PD
            # picture so tuned broke into a new picture every few lines.
            if not found and len(seg):
                n = min(sync_n, _ms_n(self.TRAIN_WIN_MS))
                found = len(seg) >= n and float(_tone_ratio(seg, 1200.0, n).max()) >= self.SYNC_MIN
            self._misses = 0 if found else self._misses + 1
            if self._misses >= self.PARTIAL_LOST:
                del self._rows[len(self._rows) - self._misses * (2 if k == "pd" else 1):]
                self._finish_image()
                return False
        if self._line >= spec["height"] // (2 if k == "pd" else 1):
            self._finish_image()
        return True

    def _pixels(self, abs_start: float, dur: float, n_px: int, raw: bool = False) -> np.ndarray:
        """Mean frequency over each of n_px equal parts of [abs_start,
        abs_start + dur), at fractional-sample edges (a cumulative sum,
        interpolated), mapped to 0-255."""
        edges = abs_start - self._base + dur * np.arange(n_px + 1) / n_px
        f = self._freq
        end = int(np.ceil(edges[-1])) + 1
        if end > len(f):
            f = np.concatenate([f, np.full(end - len(f), f[-1] if len(f) else 1500.0)])
        lo = max(0, int(np.floor(edges[0])))
        c = np.concatenate([[0.0], np.cumsum(f[lo:end])])
        cx = np.interp(edges - lo, np.arange(len(c)), c)
        vals = np.diff(cx) / np.maximum(np.diff(edges), 1e-9)
        if raw:
            return vals
        return np.clip((vals - 1500.0) / 800.0 * 255.0 + 0.5, 0, 255).astype(np.uint8)

    def _emit_line(self, row_rgb: np.ndarray) -> None:
        self.emit({"mode": "sstv", "state": "line", "name": self._name,
                   "line": len(self._rows),
                   "of": self._spec["height"],
                   "row": base64.b64encode(row_rgb.astype(np.uint8).tobytes()).decode("ascii")})

    def _finish_image(self) -> None:
        self._state = "idle"
        self._sync_seen = self._base + len(self._audio)
        if not self._rows:
            self.emit({"mode": "sstv", "state": "done", "name": self._name, "path": ""})
            return
        if self._spec["kind"] == "robot":
            rgb = np.stack([_yryby_to_rgb(y, ry, by) for y, ry, by in self._rows])
        else:
            rgb = np.stack(self._rows)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / self._name
        _write_png(path, rgb)
        self.emit({"mode": "sstv", "state": "done", "name": self._name, "path": str(path)})
