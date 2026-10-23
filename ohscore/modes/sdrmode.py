"""A mode decoder that is a shack_sdr session (RADIO-SDR-PLAN §4.3).

From milestone 1 RTTY is decoded by shack_sdr's Rust decoder, and from
milestone 2 PSK31/63/125 and SSTV are too, in both apps, because the mode
table is shared. The engine still drives it as it
drives every mode decoder - `feed(audio, t)` on the decode thread with the
demodulated 12 kHz audio, `close()` when the mode changes - and it still
speaks today's `events` items ({"mode": "rtty", "text": ..., "center": ...}),
so the window's panels, Remote and Enable TX's reply logic see no change.
What changed is underneath: `feed` copies the block into the session's
ring in shack_sdr's host and returns, a Rust worker thread decodes with the
GIL released, and the results come back through `poll`.

Two ways to run:

- **Inside an engine** (`link=` the engine's Decoders.link()): the session
  lives in the engine's one host, pinned so the CPU budget never pauses
  it, and is listed as the session "vfo". The engine's supervisor polls
  the host ten times a second and hands this session's results to
  `deliver`.
- **On its own** (no link: a test, the store image's selftest, a tool
  decoding a file): the decoder makes a host of its own, with a ring long
  enough for a whole recording fed faster than real time, polls it after
  every feed, and `drain()` waits for the last results.

The Python decoders these replace - rtty.Decoder, psk.Decoder and
sstv.Decoder - were removed once their scores were captured as golden
numbers in ohs-libs (shack_sdr testdata/rtty, testdata/psk and
testdata/sstv), which the Rust decoders are held to never fall below. The
encoders stay where they were (rtty.Encoder, psk.Encoder, sstv.Encoder):
transmit is unchanged.

Each decoder still speaks its mode's `events` in the shapes the window's
panels and Remote already read (PskDecoder, SstvDecoder below say how
each is mapped), and adds only what is new: a PSK character's `channel`,
an SSTV picture's `file`.
"""
from __future__ import annotations

import base64
import math
import time
from typing import Callable

import numpy as np

from .. import sdr

FS = 12_000.0

# A host made for one decoder on its own holds this much audio before it
# drops the oldest: a test or a tool feeds a whole recording at once.
OWN_RING_S = 600.0

# PSK: where the host's adapter centres the audio it turns into IQ - the
# middle of the 100-3000 Hz digital passband every mode hears
# (dsp/demod.py DIGITAL_FILTER) - so a channel anywhere in that passband
# is a small offset from it. shack_sdr refuses a centre of 0 (bad_input
# "centre"), which would otherwise have let the channels be audio
# frequencies as they are.
PSK_AUDIO_CENTRE = 1500.0
# The most channels one PSK session decodes (shack_sdr README "PSK").
PSK_MAX_CHANNELS = 16
# Channels closer than this are one channel: a second click on a signal
# already decoded must not start a second decoder on it.
PSK_SAME_HZ = 5.0


class HostedDecoder:
    """`decoder` (a shack_sdr catalogue id) fed the engine's audio, with the
    signal at `center` Hz in it. `mode` is the engine mode its events name."""

    def __init__(self, emit: Callable[[dict], None], *, decoder: str, mode: str, center: float = 1000.0,
                 params: dict | None = None, link=None, host_center: float | None = None,
                 files_dir: str | None = None, **_opts):
        m = sdr.load()
        if m is None:
            raise RuntimeError(sdr.why())
        self.emit = emit
        self.mode = mode
        self.center = float(center)
        self.decoder = decoder
        self.params = dict(params or {})
        self._link = link
        self._own = None
        if link is None:
            # A decoder that saves pictures (SSTV) keeps them in `files_dir`
            # when it runs on its own, as the engine's host keeps them in
            # the app's data folder (decoders.py).
            extra = {"files_dir": str(files_dir)} if files_dir else {}
            self._own = m.Host(threads=1, cpu_max=0.0, ring_s=OWN_RING_S, max_sessions=1, **extra)
            host = self._own
        else:
            host = link.host
        self._host = host
        self._error = m.DecoderError
        # Where the host's analytic adapter puts the signal: the signal's own
        # centre for a one-signal decoder (RTTY), the middle of the audio
        # passband for one that hears several (PSK's channels).
        self.host_center = self.center if host_center is None else float(host_center)
        self.sid = host.start(decoder, self.params, input="audio", rate=FS, center_hz=self.host_center, pinned=True)
        if link is not None:
            link.attach(self.sid, self)
        self._index = 0
        self._text = ""
        self.last_rev = 0

    # -- what the engine calls -------------------------------------------------

    def feed(self, audio: np.ndarray, t: float) -> None:
        a = np.asarray(audio, dtype=np.float32)
        try:
            self._host.feed(self.sid, a, float(t), self._index)
        except self._error:
            return          # the host closed under us (the radio stopping): nothing more to decode
        self._index += len(a)
        if self._own is not None:
            self._poll_own()

    def reset(self) -> None:
        try:
            self._host.reset(self.sid)
        except self._error:
            pass
        self._text = ""

    def retire(self) -> None:
        """The engine has replaced this decoder (a mode change). Its session
        stops now, not when the decode thread next gets round to closing
        retired decoders - which, in a mode with no decoder, is not until
        the radio stops - so the Decoders view never lists a "vfo" that is
        no longer the mode. Safe to call twice, and before close()."""
        if self._link is not None:
            self._link.detach(self.sid)
            self._link = None
        try:
            self._host.stop(self.sid)
        except self._error:
            pass

    def close(self) -> None:
        self.retire()
        if self._own is not None:
            self._own.close()
            self._own = None

    # -- results -----------------------------------------------------------------

    def deliver(self, item: dict) -> None:
        """One result of this session's (the engine's supervisor, or our own
        poll): text becomes the mode's event, as the Python decoder sent it."""
        self.last_rev = item.get("rev", self.last_rev)
        if item.get("type") != "text":
            return
        text = item.get("text") or ""
        if not text:
            return
        self._text += text
        ev = {"mode": self.mode, "text": text, "center": self.center}
        if item.get("offsetHz") is not None:
            ev["offsetHz"] = round(float(item["offsetHz"]), 1)
        if item.get("snrDb") is not None:
            ev["snr"] = round(float(item["snrDb"]), 1)
        self.emit(ev)

    def _poll_own(self) -> int:
        n = 0
        for item in self._own.poll(500):
            if item.get("session") == self.sid:
                self.deliver(item)
                n += 1
        return n

    def drain(self, quiet_s: float = 0.4, timeout: float = 20.0) -> None:
        """On its own: wait until the decoder has worked through everything
        fed and the results have stopped coming (`quiet_s` with none)."""
        if self._own is None:
            return
        end = time.monotonic() + timeout
        last = time.monotonic()
        seen = (-1, -1, -1, -1)
        while time.monotonic() < end:
            got = self._poll_own()
            status = self._host.status(self.sid)
            st = status["stats"]
            # Progress in any decoder: its results (rev), what is still
            # queued for it, and RTTY's frame counters (a frame rejected
            # by the squelch is work with no result).
            now = (status.get("rev", 0), self._own.stats().get("queued", 0), st.get("frames", 0),
                   st.get("rejected", 0))
            if got or now != seen or now[1]:
                last = time.monotonic()
                seen = now
            elif time.monotonic() - last >= quiet_s:
                return
            time.sleep(0.02)

    def status(self) -> dict:
        try:
            return self._host.status(self.sid)
        except self._error:
            return {}

    @property
    def text(self) -> str:
        """Everything printed so far (after drain(), on its own)."""
        return self._text


def rtty_decoder(emit: Callable[[dict], None], center: float = 1000.0, link=None, **opts) -> HostedDecoder:
    """The RTTY mode decoder: 45.45 Bd, 170 Hz, ITA2 with the US-TTY
    figures, unshift-on-space, AFC and squelch - shack_sdr's defaults, which
    are what the Python decoder did and what every amateur RTTY station
    sends. Other speeds and shifts are a fixed session's (Decoders view)."""
    return HostedDecoder(emit, decoder="rtty", mode="rtty", center=center, link=link)


class PskDecoder(HostedDecoder):
    """PSK31, PSK63 and PSK125: shack_sdr's `psk` decoder, which hears
    several stations at once. The mode's own station is the channel at
    `center` (the registry's offset, where a click on the scope puts a
    signal); `channels` are more stations, audio frequencies in Hz, as the
    engine's pskChannels holds them and a click on the zoom adds them.

    Each character leaves as the Python decoder sent it - {"mode", "text",
    "center", "df", "snr"}, `center` and `df` the audio frequency the
    decoder is tracking that station on - plus `channel`, the audio
    frequency of the channel it belongs to, so a client can give each
    station a line of its own. `snr` keeps its old meaning, the SNR in the
    symbol's own bandwidth: shack_sdr gives it in 2.5 kHz, so the
    bandwidth ratio is added back."""

    def __init__(self, emit: Callable[[dict], None], *, variant: str = "psk31", center: float = 1000.0,
                 channels=(), link=None, **opts):
        from . import psk
        self.variant = variant
        self.baud = psk.BAUDS[variant]
        self._centre_hz = float(center)
        self._extra = self._clean(channels)
        super().__init__(emit, decoder="psk", mode=variant, center=center,
                         params={"baud": self.baud, "channels": self._param()}, link=link,
                         host_center=PSK_AUDIO_CENTRE, **opts)
        # The decoder's latest view of each channel (its `meta`), in audio Hz.
        self.heard: list[dict] = []

    def _clean(self, channels) -> list[float]:
        """The extra channels as the decoder takes them: numbers, none on
        the mode's own channel or on each other, at most 15 beside it."""
        out: list[float] = []
        for c in channels or ():
            try:
                f = float(c)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(f) or any(abs(f - g) < PSK_SAME_HZ for g in [self._centre_hz, *out]):
                continue
            out.append(round(f, 1))
            if len(out) >= PSK_MAX_CHANNELS - 1:
                break
        return out

    @property
    def channels(self) -> list[float]:
        """Every channel decoded, in audio Hz: the mode's own first."""
        return [self._centre_hz, *self._extra]

    def _param(self) -> str:
        return ",".join(f"{c - PSK_AUDIO_CENTRE:g}" for c in self.channels)

    def set_channels(self, channels) -> None:
        """The engine's pskChannels changed: the session follows live (a
        channel kept in the new list keeps its lock and its text)."""
        want = self._clean(channels)
        if want == self._extra:
            return
        self._extra = want
        self.params["channels"] = self._param()
        try:
            self._host.configure(self.sid, {"channels": self.params["channels"]})
        except self._error:
            pass

    def _nearest(self, audio_hz: float) -> float:
        return min(self.channels, key=lambda c: abs(c - audio_hz))

    def deliver(self, item: dict) -> None:
        self.last_rev = item.get("rev", self.last_rev)
        kind = item.get("type")
        if kind == "meta":
            rows = (item.get("fields") or {}).get("channels")
            if isinstance(rows, list):
                self.heard = [{"channel": round(PSK_AUDIO_CENTRE + float(r.get("offsetHz") or 0.0), 1),
                               "freq": round(PSK_AUDIO_CENTRE + float(r.get("freqHz") or 0.0), 1),
                               "sync": bool(r.get("sync")), "snrDb": r.get("snrDb"), "imdDb": r.get("imdDb")}
                              for r in rows if isinstance(r, dict)]
            return
        if kind != "text" or not item.get("text"):
            return
        text = item["text"]
        self._text += text
        audio = PSK_AUDIO_CENTRE + float(item.get("offsetHz") or 0.0)
        ev = {"mode": self.mode, "text": text, "center": round(audio, 1), "df": round(audio, 1),
              "channel": self._nearest(audio)}
        if item.get("snrDb") is not None:
            ev["snr"] = round(float(item["snrDb"]) + 10 * math.log10(2500.0 / self.baud), 1)
        self.emit(ev)


class SstvDecoder(HostedDecoder):
    """SSTV: shack_sdr's `sstv` decoder (fourteen modes, from a VIS header
    or from line syncs). Its pictures arrive as `image` results; this
    turns them into the events sstv.py sent, which the SSTV panel and
    Remote paint from:

        {"mode": "sstv", "state": "start", "name", "fmt", "width", "height"[, "partial"]}
        {"mode": "sstv", "state": "line", "name", "line", "of", "row"}   (line counts from 1; row is
                                                                          base64 of width x 3 RGB bytes)
        {"mode": "sstv", "state": "done", "name", "path", "file"}

    `fmt` is shack_sdr's mode id ("martin1", "pd120"), which sstv.py spelt
    differently ("martinm1"); `file` is new: the name api/decoders/files
    serves the picture by. A row may come again - the decoder straightens
    the picture when it ends and sends the rows that moved - and a painter
    simply paints it again. A header for a mode not decoded, or one too
    weak to read, is {"mode": "sstv", "state": "unsupported" | "bad_vis",
    "fmt"}: no picture follows.

    The start waits for the decoder's first `meta`, which names the mode
    (the image's own start does not), unless rows come first."""

    def __init__(self, emit: Callable[[dict], None], *, out_dir: str | None = None, link=None, **opts):
        self._n = 0
        self._pic: dict | None = None
        super().__init__(emit, decoder="sstv", mode="sstv", center=1900.0, link=link, files_dir=out_dir,
                         **opts)

    def _begin(self, fmt: str = "", partial: bool = False) -> None:
        pic = self._pic
        if pic is None or pic["name"]:
            return
        self._n += 1
        pic["name"] = f"sstv_{fmt or 'picture'}_{self._n:04d}"
        ev = {"mode": "sstv", "state": "start", "name": pic["name"], "fmt": fmt, "width": pic["w"],
              "height": pic["h"]}
        if partial:
            ev["partial"] = True
        self.emit(ev)

    def deliver(self, item: dict) -> None:
        self.last_rev = item.get("rev", self.last_rev)
        kind = item.get("type")
        if kind == "meta":
            f = item.get("fields") or {}
            state = f.get("state")
            if state == "receiving" and self._pic is not None:
                self._begin(str(f.get("mode") or ""), bool(f.get("partial")))
            elif state == "bad_vis" or (state == "unsupported" and f.get("mode")):
                # A header for a mode it does not decode is worth a word
                # only when it names one: a code in no table (the decoder
                # reads VIS 127 in the silence after a picture) is noise.
                self.emit({"mode": "sstv", "state": state, "fmt": str(f.get("mode") or "")})
            return
        if kind != "image":
            return
        event = item.get("event")
        if event == "start":
            self._pic = {"w": int(item.get("width") or 0), "h": int(item.get("height") or 0), "name": None}
            return
        pic = self._pic
        if pic is None:
            return
        self._begin()
        if event == "lines":
            rgb = item.get("rgb") or b""
            stride = pic["w"] * 3
            first = int(item.get("from") or 0)
            for k in range(len(rgb) // stride if stride else 0):
                self.emit({"mode": "sstv", "state": "line", "name": pic["name"], "line": first + k + 1,
                           "of": pic["h"],
                           "row": base64.b64encode(rgb[k * stride:(k + 1) * stride]).decode("ascii")})
        elif event == "done":
            self.emit({"mode": "sstv", "state": "done", "name": pic["name"], "path": item.get("path") or "",
                       "file": item.get("file") or ""})
            self._pic = None

    def reset(self) -> None:
        super().reset()
        self._pic = None


def psk_decoder(emit: Callable[[dict], None], variant: str = "psk31", center: float = 1000.0, channels=(),
                link=None, **opts) -> PskDecoder:
    """The PSK31/63/125 mode decoder (PskDecoder)."""
    return PskDecoder(emit, variant=variant, center=center, channels=channels, link=link)


def sstv_decoder(emit: Callable[[dict], None], out_dir: str | None = None, link=None, **opts) -> SstvDecoder:
    """The SSTV mode decoder (SstvDecoder): pictures into `out_dir` when it
    runs on its own; in an engine, into the engine host's files folder."""
    return SstvDecoder(emit, out_dir=out_dir, link=link)
