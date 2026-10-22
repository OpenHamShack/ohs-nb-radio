"""A receive-only device that plays a SigMF recording (ohscore/sigmf.py).

Why a device and not a special mode of the engine: the recorder keeps the
device's own stream (after any software decimation, before the converter
mirror and the noise blanker), so a file can stand in for the radio behind
the same interface, and everything after `read()` - scopes, beacon lock,
demodulators, decoders - is exactly what runs on air. The engine knows only
three things about it (Engine.start_playback): it is chosen instead of the
configured device, it keeps its own clock, and it cannot transmit.

Decisions:

- **Frequencies are matched on the air, not in device terms.** Each
  capture's `core:frequency` is where its DC was on the air (for OpenHamShack
  NB: the LNB's nominal downlink, before rxCorr). The app tunes in device
  terms through its own converter, which may not be the recorder's (another
  LNB LO, a transverter), so the request is turned into an on-air frequency
  with the converter the app works through (`set_rx_converter`), and the
  difference is made up digitally: an NCO shift, phase-continuous across
  blocks. A capture carries its own frequency, so a recording made while
  NB re-centred, or HAM changed band, plays right on both sides of it.
- **Tuning outside the recording is refused**, with a sentence, as a radio
  refuses a frequency it cannot reach (DeviceError from set_rx_if, and
  `rx_range` for the apps that check it before tuning). The edge is
  SPAN x fs either side of the captures' centres: past it most of the
  receiver's span would be outside what was recorded. Within it, what lies
  beyond the recording's own edge wraps round from the other side - an NCO
  cannot invent samples; QO-100 NB never moves DC more than tens of kHz,
  and OpenHamShack Radio plans the same centre the recorder had.
- **Mirroring**: `openhamshack:inverted` says the file's spectrum is mirrored
  relative to the air; it is put the right way up, then mirrored again if
  the app's own converter inverts (the engine will undo that).
- **The recording's clock, not the wall clock.** `utc_end` is the UTC just
  after the last sample read, from each capture's `core:datetime`, so FT8
  and FT4 slots line up with when the signals were really sent. A gap the
  file marks is played as silence of its own length, up to GAP_FILL_S, so
  the timeline (and the real-time pacing) carries on through it; a longer
  one (a reconnect) is cut short and the clock jumps, at a block boundary
  so no block straddles two times. A loop adds whole minutes to the clock
  rather than going back: slots keep their second-of-minute and parity,
  and nothing downstream sees time run backwards.
- **Real time by default** (paced against the monotonic clock from the
  first read, like the simulator); `realtime=False` plays as fast as the
  receiver takes it, for tests and analysis.
- At the end, without looping, it delivers silence and says `ended`; the
  engine tells the operator, and returning to the radio is theirs to
  choose - it may open real hardware.

Datatypes: ci16_le (ours), cf32_le, ci8, cu8 and their big-endian forms
from sigmf.DTYPES; one channel only. `openhamshack:scale` (ours) overrides the
datatype's full scale.

The rule for frequencies has one exception, for the hand-made recordings
of 07/10/2026 from before the recorder existed: when the global object
has `openhamshack:lnb_lo_hz`, `core:frequency` is the LNB's output (the SDR's
frequency) and the LO is added to put it on the air.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

from .. import sigmf
from .base import Device, DeviceError
from ..i18n.text import _

SPAN = 0.45          # x fs either side of a capture's centre: how far DC may be tuned
GAP_FILL_S = 15.0    # a gap up to this long is played as silence; longer ones are cut short
LOOP_STEP_S = 60.0   # a loop moves the clock on by whole multiples of this (FT8, FT4 and parity line up)


class Segment:
    """One capture: samples [start, end) of the file, DC at `air` Hz on the
    air (None: the file does not say), its first sample at `utc`, after a
    gap of `gap` seconds."""

    __slots__ = ("start", "end", "air", "utc", "gap")

    def __init__(self, start: int, end: int, air, utc: float, gap: float):
        self.start, self.end, self.air, self.utc, self.gap = start, end, air, utc, gap


class FileDevice(Device):
    kind = "file"
    can_tx = False
    radiates = False            # nothing here can reach an antenna
    own_clock = True            # Engine: stamp receive with utc_end, not the wall clock
    # What the engine says when keying is asked for (Engine._tx_blocked).
    tx_refusal = "Playing a recording: there is no transmitter (File › Back to the radio)"

    def __init__(self, path, conv=None, loop: bool = False, realtime: bool = True):
        self.data_path, self.meta_path = sigmf.paths(Path(path))
        self.name = self.data_path.name[:-len(sigmf.DATA_SUFFIX)]
        # A file another program wrote may use a namespace it never
        # declared; that does not stop it playing.
        self.meta = sigmf.read_meta(self.data_path, strict=False)
        g = self.meta["global"]
        dt = g["core:datatype"]
        if dt not in sigmf.DTYPES:
            raise ValueError(_("{file}: samples of type {type} cannot be played (complex ones can: {types})").format(
                file=self.meta_path.name, type=dt, types=", ".join(sigmf.DTYPES)))
        if int(g.get("core:num_channels", 1) or 1) != 1:
            raise ValueError(_("{file} holds {n} channels; only one can be played").format(
                file=self.meta_path.name, n=g["core:num_channels"]))
        self.fs = float(g.get("core:sample_rate") or 0)
        if self.fs <= 0:
            raise ValueError(_("{file} does not say its sample rate").format(file=self.meta_path.name))
        comp, scale = sigmf.DTYPES[dt]
        self.comp = np.dtype(comp)
        self.offset = 127.5 if dt == "cu8" else 0.0
        self.scale = 1.0 / float(g["openhamshack:scale"]) if g.get("openhamshack:scale") else scale
        try:
            nbytes = self.data_path.stat().st_size
        except OSError:
            raise ValueError(_("{file} is missing: a recording needs both its .sigmf-meta and its .sigmf-data").format(
                file=self.data_path.name)) from None
        self.total = nbytes // (2 * self.comp.itemsize)
        if self.total < 1:
            raise ValueError(_("{file} holds no samples").format(file=self.data_path.name))
        self.inverted = bool(g.get("openhamshack:inverted", False))
        self.segs = self._segments(g, self.meta["captures"])
        self.length_s = self.total / self.fs
        self.conv = conv
        self.loop = bool(loop)
        self.realtime = bool(realtime)
        self.rx_if = None
        self.f = None
        self.opened = False
        self._rewind()
        self._set_range()

    def _segments(self, g: dict, caps: list) -> list[Segment]:
        lnb = float(g["openhamshack:lnb_lo_hz"]) if g.get("openhamshack:lnb_lo_hz") else 0.0
        caps = [c for c in caps if c["core:sample_start"] < self.total] or [{"core:sample_start": 0}]
        if caps[0]["core:sample_start"] != 0:
            caps = [{**caps[0], "core:sample_start": 0}] + caps[1:]
        segs: list[Segment] = []
        for i, c in enumerate(caps):
            start = c["core:sample_start"]
            end = caps[i + 1]["core:sample_start"] if i + 1 < len(caps) else self.total
            f = c.get("core:frequency")
            air = float(f) + lnb if isinstance(f, (int, float)) else (segs[-1].air if segs else None)
            gap = 0.0
            if "core:datetime" in c:
                utc = sigmf.parse_utc(c["core:datetime"])
                if segs:
                    gap = max(0.0, utc - (segs[-1].utc + (segs[-1].end - segs[-1].start) / self.fs))
            elif segs:
                gap = float(c.get("openhamshack:gap_samples", 0) or 0) / self.fs
                utc = segs[-1].utc + (segs[-1].end - segs[-1].start) / self.fs + gap
            else:
                # No time at all: now, so slots still fall somewhere sane.
                utc = time.time()
            segs.append(Segment(start, end, air, utc, gap))
        return segs

    # -- what the file covers -------------------------------------------------
    def air_span(self) -> tuple[float, float] | None:
        """On-air frequencies DC may be tuned to: SPAN x fs round the
        captures' centres. None when the file does not say where it was."""
        airs = [s.air for s in self.segs if s.air is not None]
        if not airs:
            return None
        h = SPAN * self.fs
        return min(airs) - h, max(airs) + h

    def _air(self, hz: float) -> float:
        return self.conv.air(hz) if self.conv is not None else hz

    def _set_range(self) -> None:
        # rx_range is in the device's terms (OpenHamShack Radio checks a dial
        # against it and plans its centre inside it).
        span = self.air_span()
        if span is None:
            self.rx_range = (0.0, 6e9)
            return
        if self.conv is None:
            self.rx_range = span
        else:
            self.rx_range = self.conv.radio_range(*span)

    def set_rx_converter(self, conv) -> None:
        self.conv = conv
        self._set_range()

    # -- the device interface -------------------------------------------------
    def open(self) -> None:
        if self.opened:
            return
        try:
            self.f = open(self.data_path, "rb")
        except OSError as e:
            raise DeviceError(f"Could not open {self.data_path.name} ({e})") from e
        self.reading = False
        self.opened = True

    def close(self) -> None:
        self.opened = False
        f, self.f = self.f, None
        if f is not None:
            f.close()

    def set_rx_if(self, hz: float) -> None:
        want = self._air(float(hz))
        span = self.air_span()
        if span is not None and not span[0] <= want <= span[1]:
            raise DeviceError(f"{want / 1e6:.6f} MHz is outside the recording, which covers "
                              f"{span[0] / 1e6:.6f}-{span[1] / 1e6:.6f} MHz")
        self.rx_if = float(hz)

    def set_rx_gain(self, mode: str, db: float) -> None:
        # The gain was the recording's; nothing here can change it.
        pass

    def _rewind(self) -> None:
        self.seg_i = 0
        self.pos = 0                # next file sample
        self.gap_left = int(round(self.segs[0].gap * self.fs))
        # The clock: a base UTC and the samples delivered since it, rather
        # than a sum of block lengths, which drifts by microseconds a minute.
        self.t_base, self.k_since = self.segs[0].utc, 0
        self.n = 0                  # samples delivered, silence included
        self.loops = 0
        self.phase = 0.0
        self.ended = False
        self.jump = None            # a clock jump waiting for the next block: ("seg", utc) or ("loop", None)
        self.clock_off = 0.0        # added to the recording's UTC since the last loop

    def _samples(self, a: int, b: int) -> np.ndarray:
        self.f.seek(a * 2 * self.comp.itemsize)
        raw = np.fromfile(self.f, self.comp, 2 * (b - a))
        if len(raw) < 2 * (b - a):
            raise DeviceError(f"{self.data_path.name} ended early: was it still being written?")
        v = raw.astype(np.float32)
        if self.offset:
            v -= np.float32(self.offset)
        z = (v[0::2] + 1j * v[1::2]).astype(np.complex64) * np.float32(self.scale)
        return np.conj(z) if self.inverted else z

    def _shift(self, z: np.ndarray, seg: Segment) -> np.ndarray:
        if seg.air is None or self.rx_if is None:
            return z
        df = seg.air - self._air(self.rx_if)
        if df:
            w = 2 * math.pi * df / self.fs
            z = z * np.exp(1j * (self.phase + w * np.arange(len(z)))).astype(np.complex64)
            self.phase = (self.phase + w * len(z)) % (2 * math.pi)
        return z

    def _next_segment(self) -> None:
        """Move on to the next capture; at the last, loop or end."""
        if self.seg_i + 1 < len(self.segs):
            self.seg_i += 1
            seg = self.segs[self.seg_i]
            if seg.gap <= GAP_FILL_S:
                self.gap_left = int(round(seg.gap * self.fs))
            else:
                self.jump = ("seg", seg.utc)
        elif self.loop:
            self._wrap()
        else:
            self.ended = True

    def _wrap(self) -> None:
        self.loops += 1
        self.seg_i, self.pos, self.gap_left, self.ended = 0, 0, 0, False
        self.jump = ("loop", None)

    def _apply_jump(self) -> None:
        kind, utc = self.jump
        self.jump = None
        if kind == "loop":
            # Whole minutes on from where the clock is, never back.
            first = self.segs[0].utc
            self.clock_off = math.ceil((self.t_next - first) / LOOP_STEP_S) * LOOP_STEP_S
            self.t_base = first + self.clock_off
        else:
            self.t_base = utc + self.clock_off
        self.k_since = 0

    @property
    def t_next(self) -> float:
        """UTC of the next sample to be delivered."""
        return self.t_base + self.k_since / self.fs

    def read(self, n: int) -> np.ndarray:
        if not self.opened:
            raise DeviceError("The recording is not open")
        if not self.reading:
            self.reading = True
            self.t_wall0 = time.monotonic() - self.n / self.fs
        if self.ended and self.loop:
            self._wrap()             # looping switched on after the end
        if self.jump is not None:
            self._apply_jump()
        out = np.zeros(n, np.complex64)
        i = 0
        while i < n and not self.ended:
            if self.jump is not None:
                break                    # the rest of this block is silence; the clock jumps after it
            if self.gap_left:
                k = min(self.gap_left, n - i)
                self.gap_left -= k
                i += k
                continue
            seg = self.segs[self.seg_i]
            if self.pos < seg.start:
                self.pos = seg.start
            k = min(seg.end - self.pos, n - i)
            if k > 0:
                out[i:i + k] = self._shift(self._samples(self.pos, self.pos + k), seg)
                self.pos += k
                i += k
            if self.pos >= seg.end:
                self._next_segment()
        if self.conv is not None and self.conv.inverted:
            out = np.conj(out)
        self.n += n
        self.k_since += n
        self.utc_end = self.t_next
        if self.realtime:
            lag = self.t_wall0 + self.n / self.fs - time.monotonic()
            if lag > 0:
                time.sleep(lag)
        return out

    # -- where it is ------------------------------------------------------------
    def recorded_utc(self) -> float:
        """The recording's own UTC at the playing position (without any
        loop's whole minutes)."""
        seg = self.segs[min(self.seg_i, len(self.segs) - 1)]
        return seg.utc + (max(self.pos, seg.start) - seg.start) / self.fs

    def status(self) -> dict:
        return {"kind": self.kind, "file": self.name, "pos": round(self.pos / self.fs, 1),
                "length": round(self.length_s, 1), "utc": round(self.recorded_utc(), 1), "loop": self.loop,
                "ended": self.ended, "loops": self.loops}
