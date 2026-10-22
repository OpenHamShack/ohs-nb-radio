"""A mode decoder that is a shack_sdr session (RADIO-SDR-PLAN §4.3).

From milestone 1 RTTY is decoded by shack_sdr's Rust decoder, in both
apps, because the mode table is shared. The engine still drives it as it
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

The Python decoder this replaces, rtty.Decoder, was removed once its scores
were captured as golden numbers in ohs-libs (shack_sdr testdata/rtty/
golden.json, from this repository's 74241d3), which the Rust decoder is held
to never fall below. rtty.Encoder stays: transmit is unchanged.
"""
from __future__ import annotations

import time
from typing import Callable

import numpy as np

from .. import sdr

FS = 12_000.0

# A host made for one decoder on its own holds this much audio before it
# drops the oldest: a test or a tool feeds a whole recording at once.
OWN_RING_S = 600.0


class HostedDecoder:
    """`decoder` (a shack_sdr catalogue id) fed the engine's audio, with the
    signal at `center` Hz in it. `mode` is the engine mode its events name."""

    def __init__(self, emit: Callable[[dict], None], *, decoder: str, mode: str, center: float = 1000.0,
                 params: dict | None = None, link=None, **_opts):
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
            self._own = m.Host(threads=1, cpu_max=0.0, ring_s=OWN_RING_S, max_sessions=1)
            host = self._own
        else:
            host = link.host
        self._host = host
        self._error = m.DecoderError
        self.sid = host.start(decoder, self.params, input="audio", rate=FS, center_hz=self.center, pinned=True)
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
        seen = (-1, -1)
        while time.monotonic() < end:
            got = self._poll_own()
            st = self._host.status(self.sid)["stats"]
            now = (st.get("frames", 0), st.get("rejected", 0))
            if got or now != seen:
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
