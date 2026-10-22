"""KG-STV pictures as something an engine sends: a picture and a callsign
line in, the over's 12 kHz audio out - and, the other way, an audio
receiver for a radio tuned to a KG-STV signal.

The air interface and the picture coding are ohscore/dsp/kgstv.py, which
says where each fact came from (KG-STV's readme, real signal, kgstv.exe's
own decoder; docs/kgstv-research.md). Everything sent here is built from
the same tables and layout that NB's receiver reads, so an over is the
receiver's exact inverse; tests/test_kgstv_tx.py proves it by sending
pictures through that receiver.

An over, as the stations heard on QO-100 send one (DL4CQ, DG8RP; the
readme's defaults):

- MSK, uncoded (KG-STV's "MSK/NORM"): what every uncoded station heard on
  QO-100 used, and the mode whose every detail was checked on air. The
  coded variant (VU2SAA's) decodes too, but only its information chunk is
  certain to be coded the way the program does it.
- 1200 baud, a 1 at 1800 Hz and a 0 at 1200 Hz in USB audio, phase
  continuous: KG-STV's tones, so a KG-STV station on the same dial hears
  it where it expects (its waterfall's markers are 1200 and 1800 Hz).
- The 256-bit 0101 preamble; the callsign line five times; the 300 blocks
  in rows with the callsign line after every tenth; the end frame
  END_REPEATS times.
- JPEG scale index 10 (x1.0) unless asked otherwise: what every station
  heard used. The program itself offers the scale as its picture quality
  beside the over's length ("TxTime"), and so does NB's dialog (QUALITIES).
- The callsign line is free text in KG-STV (its Callsign box): stations
  put their call, often a name and their locator, in it ("DG8RW JN69CV",
  "PA3EKI - Jack - JO21GW" on ohs-box, 11-12/10/2026). Here it is the
  station's callsign and locator from its settings, `header()`.

    tx = Transmission(fit_picture(rgb), header("GM4BRI", "IO75RL"))
    tx.seconds, tx.blocks_sent(t), tx.audio(), tx.preview()
    audio = Encoder().render(picture=rgb, callsign=..., locator=..., scale=10)

    dec = Decoder(emit)            # 12 kHz USB audio, KG-STV's tones at 1200-1800 Hz
    dec.feed(audio, t)             # -> emit({"state": "start" | "block" | "done" | "call" | "text", ...})
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from ..dsp import kgstv as codec
from ..dsp.fir import OlsFilter, lowpass
from ..i18n.text import _

AUDIO_RATE = 12_000.0
CENTRE = codec.CENTRE_HZ
STANDARD = 10                   # the scale index (x1.0) every station heard on QO-100 used
# The qualities NB offers, finest first: the scale index's multiplier of
# JPEG's "quality 50" tables. Finer than x0.6 roughly doubles a busy
# picture's over for detail QO-100's ~5 dB-SNR pictures do not show, and
# can overrun the default 300 s transmit time-out (PA3EKI's picture: 322 s
# at x0.1); coarser than x2.0 saves little, since a frame's sync and header
# are 171 bits whatever its block holds.
QUALITIES = (8, STANDARD, 12, 15)
CALL_REPEATS = 5                # the readme's default (1-12 from build 004); DL4CQ and DG8RP sent five
CALL_EVERY = 10
# The readme's default is three; every station heard sent ten. Five keeps
# a receiver that misses a couple (a fade, the transponder's AGC) from
# waiting out its 30 s time-out, for 0.4 s more than three.
END_REPEATS = 5
RAMP_S = 0.005                  # raised-cosine edges: no key clicks either side of the tones
# After the last end frame, more of the preamble's 0101 (27 ms). Without it
# the last frame's final bits fall in the fade-out and in the receiver's
# filter and bit-clock settling as the signal stops, and its unterminated
# convolutional code has nothing to lean on there: NB's own receiver lost
# that frame on a clean signal. A real station's transmitter chain smears
# its end the same way.
TAIL_BITS = 32
LEVEL = 0.9                     # the over's peak, as the other rendered modes
# MSK's spectrum falls off only as f^-4 outside its main lobe (1500 +-900 Hz
# here), so how wide "99.5 % of the power" is - what the engine measures
# and the band plan judges - swung from 2.3 to 5.6 kHz with the picture's
# content: a busy photograph at x0.6 measured 2.8 kHz and would have been
# refused in the 2.7 kHz digimode segment it belongs in. A gentle band-pass
# over the main lobe (-6 dB at 1500 +-BANDPASS_HZ) holds it to about
# 1.8 kHz whatever is sent - the SSB filter on any KG-STV station's
# transmitter does as much - and changes nothing a receiver sees: NB's own
# channel is +-1.2 kHz, and every test of the receiver passes through it.
BANDPASS_HZ = 800.0
BANDPASS_TAPS = 255
HEADER_MAX = 40                 # characters: the program's box is free text; a line, not a message


def header(callsign: str, locator: str = "") -> str:
    """The callsign line an over carries: the call and, when the station
    has one, its locator, as most stations heard put them ("DG8RW
    JN69CV"). Raises ValueError without a callsign - KG-STV itself will
    not send without one ("Set your callsign") - or with characters a
    receiver could not show (the line is ASCII on the air)."""
    call = " ".join(str(callsign or "").split()).upper()
    loc = str(locator or "").strip()
    if not call:
        raise ValueError(_("Set your callsign (Settings › Station) before sending: KG-STV sends it with every "
                           "picture"))
    line = f"{call} {loc.upper()}" if loc else call
    if not line.isascii() or not line.isprintable():
        raise ValueError(_("A KG-STV callsign line is plain letters, digits and punctuation: {line}").format(
            line=line))
    return line[:HEADER_MAX]


# --------------------------------------------------------------------------- the picture
def fit_picture(rgb) -> np.ndarray:
    """Any picture (H x W x 3 or 4, uint8) to KG-STV's 320x240 as the
    program does it: cut to 4:3 from the middle ("the excess top and
    bottom, or left and right, is cut off" - its readme), then scaled.
    Shrinking averages each output pixel's whole area (no aliasing on a
    photograph's fine detail); enlarging interpolates."""
    a = np.asarray(rgb)
    if a.ndim != 3 or a.shape[2] < 3 or a.shape[0] < 1 or a.shape[1] < 1:
        raise ValueError(_("That is not a colour picture"))
    a = a[..., :3].astype(np.float64)
    h, w = a.shape[:2]
    want = codec.WIDTH / codec.HEIGHT
    if w / h > want:
        cw = max(1, int(round(h * want)))
        a = a[:, (w - cw) // 2:(w - cw) // 2 + cw]
    else:
        ch = max(1, int(round(w / want)))
        a = a[(h - ch) // 2:(h - ch) // 2 + ch]
    a = _resize_axis(a, codec.HEIGHT, 0)
    a = _resize_axis(a, codec.WIDTH, 1)
    return np.clip(np.rint(a), 0, 255).astype(np.uint8)


def _resize_axis(a: np.ndarray, n: int, axis: int) -> np.ndarray:
    m = a.shape[axis]
    if m == n:
        return a
    a = np.moveaxis(a, axis, 0)
    if m > n:
        # Area: the integral of the input over each output pixel's span.
        cs = np.concatenate([np.zeros((1,) + a.shape[1:]), np.cumsum(a, 0)])
        edges = np.linspace(0.0, m, n + 1)
        i = np.floor(edges).astype(int).clip(0, m - 1)
        f = (edges - i)[(...,) + (None,) * (a.ndim - 1)]
        at = cs[i] + f * (cs[i + 1] - cs[i])
        out = (at[1:] - at[:-1]) / (m / n)
    else:
        x = (np.arange(n) + 0.5) * m / n - 0.5
        i0 = np.floor(x).astype(int).clip(0, m - 1)
        i1 = (i0 + 1).clip(0, m - 1)
        f = (x - np.floor(x)).clip(0, 1)[(...,) + (None,) * (a.ndim - 1)]
        out = a[i0] * (1 - f) + a[i1] * f
    return np.moveaxis(out, 0, axis)


# --------------------------------------------------------------------------- an over
class Transmission:
    """One picture's over: its channel bits, and where each frame falls in
    them, so a progress line can say which block is on the air from the
    seconds since key-up (`blocks_sent`)."""

    def __init__(self, picture: np.ndarray, line: str, scale: int = STANDARD):
        if not 0 <= int(scale) < len(codec.SCALES):
            raise ValueError(_("KG-STV has no picture scale {scale}").format(scale=scale))
        self.picture = np.asarray(picture, np.uint8)
        self.line = line
        self.scale = int(scale)
        self.frames = codec.picture_frames(line, self.picture, self.scale, CALL_REPEATS, CALL_EVERY, END_REPEATS)
        pre = codec.preamble_bits()
        self.bits = np.concatenate([pre] + [f["bits"] for f in self.frames] + [pre[:TAIL_BITS]])
        ends, pos = [], len(pre)
        for f in self.frames:
            pos += len(f["bits"])
            if f["com"] == 1:
                ends.append(pos)
        self.block_ends = np.array(ends, np.int64)      # the bit after each block frame's last
        self.blocks = len(ends)

    @property
    def seconds(self) -> float:
        return len(self.bits) / codec.BAUD

    def blocks_sent(self, t: float) -> int:
        """How many blocks are wholly on the air `t` seconds into the audio."""
        return int(np.searchsorted(self.block_ends, t * codec.BAUD, side="right"))

    def audio(self, rate: float = AUDIO_RATE, level: float = LEVEL) -> np.ndarray:
        """The over as real USB audio at `rate` (a whole number of samples a
        bit): continuous-phase FSK on 1200/1800 Hz, band-limited to its main
        lobe (BANDPASS_HZ), raised-cosine edges, `level` at its peak."""
        sps = rate / codec.BAUD
        if abs(sps - round(sps)) > 1e-9:
            raise ValueError(_("{rate:g} Hz is not a whole number of samples per bit").format(rate=rate))
        f = CENTRE + np.repeat(np.where(self.bits > 0, codec.DEV_HZ, -codec.DEV_HZ), int(round(sps)))
        ph = 2 * np.pi * np.cumsum(f) / rate
        n = np.arange(BANDPASS_TAPS) - (BANDPASS_TAPS - 1) / 2
        h = 2.0 * lowpass(BANDPASS_HZ, rate, BANDPASS_TAPS) * np.cos(2 * np.pi * CENTRE * n / rate)
        a = _filter_same(np.sin(ph), h)
        # The fades after the filter, so the over starts and ends at silence
        # rather than at the filter's edge.
        r = int(RAMP_S * rate)
        if r and len(a) > 2 * r:
            ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(r) / r)
            a[:r] *= ramp
            a[-r:] *= ramp[::-1]
        return (a * (level / max(float(np.max(np.abs(a))), 1e-9))).astype(np.float32)

    def preview(self) -> np.ndarray:
        """The picture as a receiver will paint it: every block's data
        decoded, at the scale it was coded at."""
        out = np.zeros_like(self.picture)
        b = codec.BLOCK
        for f in self.frames:
            if f["com"] == 1:
                x, y = f["x"], f["y"]
                out[y * b:(y + 1) * b, x * b:(x + 1) * b] = codec.decode_block(f["data"], f["sc"])
        return out


def _filter_same(a: np.ndarray, h: np.ndarray) -> np.ndarray:
    """`a` through the linear-phase FIR `h`, delay taken out (same length,
    aligned), by FFT: an over is up to a few million samples."""
    n = len(a) + len(h) - 1
    m = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(a, m) * np.fft.rfft(h, m), m)[:n]
    d = (len(h) - 1) // 2
    return y[d:d + len(a)]


def fitting_scale(picture: np.ndarray, line: str, limit_s: float, want: int = STANDARD) -> int | None:
    """`want` if its over fits `limit_s` seconds, else the finest of the
    coarser QUALITIES that does; None if none does."""
    for s in [want] + [q for q in QUALITIES if q > want]:
        if Transmission(picture, line, s).seconds <= limit_s:
            return s
    return None


class Encoder:
    """The engine's renderer (ohscore/modes_glue.py): the whole over as
    12 kHz audio. The engine supplies the station's callsign and locator."""

    def render(self, picture=None, image=None, callsign: str = "", locator: str = "", scale: int = STANDARD,
               **_opts) -> np.ndarray:
        pic = picture if picture is not None else image
        if pic is None:
            raise ValueError(_("KG-STV sends a picture: none was given"))
        tx = Transmission(fit_picture(pic), header(callsign, locator), int(scale))
        return tx.audio()


# --------------------------------------------------------------------------- receive, from audio
class Decoder:
    """KG-STV heard in a radio's own 12 kHz USB audio (a receiver tuned so
    the tones sit at 1200-1800 Hz): mixed down to the receiver's complex
    baseband and low-passed as NB's channel is (ohsnb/kgstvrx.py CUTOFF),
    then the same Receiver and Pictures. Events are Pictures' with "state"
    naming them as the other picture modes' do."""

    CUTOFF = 1_200.0

    def __init__(self, emit: Callable[[dict], None], rate: float = AUDIO_RATE, **_opts):
        self.emit = emit
        self.rate = float(rate)
        self.rx = codec.Receiver(self.rate)
        self.pics = codec.Pictures()
        self.lp = OlsFilter(lowpass(self.CUTOFF, self.rate, 129))
        self.phase = 0.0

    def feed(self, audio, t: float = 0.0) -> None:
        a = np.asarray(audio, np.float64)
        if not len(a):
            return
        w = 2 * np.pi * CENTRE / self.rate
        z = a * np.exp(-1j * (self.phase + w * np.arange(len(a))))
        self.phase = (self.phase + w * len(a)) % (2 * np.pi)
        y = self.lp(z.astype(np.complex64))
        changes = []
        for ev in self.rx.feed(y):
            changes += self.pics.frame(ev)
        changes += self.pics.tick(self.rx.samples / self.rx.rate)
        for ch in changes:
            self.emit(dict(ch, state=ch["kind"]))


__all__ = ["Transmission", "Encoder", "Decoder", "header", "fit_picture", "fitting_scale", "QUALITIES", "STANDARD",
           "CALL_REPEATS", "CALL_EVERY", "END_REPEATS", "AUDIO_RATE"]
