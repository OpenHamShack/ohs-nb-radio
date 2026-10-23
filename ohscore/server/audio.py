"""Audio for the store form: the receiver's audio out to whoever listens
over the API, and a remote microphone in, instead of a sound card.

A store container has no sound card and must not want one: the person is
on a phone or a tablet. So the engine gets this backend (an
ohscore.audio.Backend, like NullAudio and PortAudio): play() hands each
block to every listener's bounded queue as 16-bit PCM, and read_mic()
takes the newest remote microphone audio, or silence. Timing is NullAudio's
real-time pacing, so the engine runs at the speed of sound with nobody
listening.

The format is announced, never assumed (GUIDE section 2, Audio): 16-bit
signed little-endian. Receive is at the engine's OUT_RATE (Radio 48 kHz
since 23/10/2026, QO-100 NB 12 kHz) and mono unless a listener asks for
two channels (`rx_format`); the microphone is 12 kHz mono (MIC_FORMAT),
as every transmit path works.

Stereo is asked for, never the default (23/10/2026): Remote builds already
installed on a Fire TV and a tablet follow the announced rate but play
every stream as one channel, so interleaved stereo would reach them as
double-speed noise. A listener that asks for two channels gets two for the
whole stream, whatever the mode: a mono block is sent as the same audio
on both sides, so the format the header promised never changes mid-stream
(a header is sent once and a mode change can come at any time). A stereo
block to a mono listener is averaged, as a mono FM receiver hears it.

A recording (ohscore/server/recording.py) taps the same blocks the
listeners get, so it is exactly what a person hears: demodulated, after the
engine's noise reduction when that is on.
"""
from __future__ import annotations

import queue
import threading

import numpy as np

from .. import audio as audio_mod

RATE = audio_mod.RATE
MIC_FORMAT = {"encoding": "s16le", "rate": RATE, "channels": 1}
CHANNELS = (1, 2)
# A listener a quarter of a second behind loses blocks rather than delay
# everyone: receive audio is live, not a recording.
LISTENER_BLOCKS = 32
MIC_SECONDS = 2.0


class StreamAudio(audio_mod.NullAudio):
    name = "stream"

    def __init__(self, realtime: bool = True):
        super().__init__(realtime=realtime)
        self._listeners: list[tuple[queue.Queue, int]] = []
        self._taps: list[tuple[object, int]] = []
        self._lock = threading.Lock()
        self.mic = audio_mod.Ring(int(RATE * MIC_SECONDS))
        self.mic_writer = ""            # the client whose microphone this is

    # ---------------------------------------------------------- out
    def rx_format(self, channels: int = 1) -> dict:
        """What a listener asking for `channels` is sent."""
        return {"encoding": "s16le", "rate": self.out_rate, "channels": int(channels)}

    def listen(self, channels: int = 1) -> queue.Queue:
        """A queue of PCM blocks in rx_format(channels)."""
        q: queue.Queue = queue.Queue(maxsize=LISTENER_BLOCKS)
        with self._lock:
            self._listeners.append((q, int(channels)))
        return q

    def unlisten(self, q: queue.Queue) -> None:
        with self._lock:
            self._listeners = [(lq, c) for lq, c in self._listeners if lq is not q]

    def listeners(self) -> int:
        with self._lock:
            return len(self._listeners)

    def tap(self, fn, channels: int = 1):
        """Call `fn(pcm)` with every block played, in rx_format(channels),
        on the engine's audio thread: it must only hand the block on (a
        recorder's push). Returns the function that removes it."""
        entry = (fn, int(channels))
        with self._lock:
            self._taps.append(entry)

        def untap():
            with self._lock:
                if entry in self._taps:
                    self._taps.remove(entry)
        return untap

    def play(self, audio):
        super().play(audio)
        with self._lock:
            qs, taps = list(self._listeners), list(self._taps)
        if not qs and not taps:
            return
        frames = audio_mod.as_frames(audio)
        made: dict[int, bytes] = {}

        def pcm(channels: int) -> bytes:
            # Each shape at most once a block, however many listeners.
            if channels not in made:
                a = frames
                if a.shape[1] != channels:
                    a = audio_mod.mono(a)[:, None] if channels == 1 else np.repeat(a[:, :1], channels, axis=1)
                made[channels] = (np.clip(a, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
            return made[channels]

        for fn, c in taps:
            fn(pcm(c))
        for q, c in qs:
            block = pcm(c)
            try:
                q.put_nowait(block)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(block)
                except (queue.Empty, queue.Full):
                    pass

    # ---------------------------------------------------------- in
    def feed_mic(self, pcm: bytes) -> None:
        a = np.frombuffer(pcm[: len(pcm) // 2 * 2], "<i2").astype(np.float32) / 32768.0
        if len(a):
            self.mic.write(a)

    def read_mic(self, n: int) -> np.ndarray:
        silence = super().read_mic(n)        # paces in real time
        if len(self.mic) >= n:
            a = self.mic.read(n)
            self.level = 20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-9)
            return a
        return silence

    def status(self):
        return {"backend": "stream", "played": self.played, "listeners": self.listeners(), "outRate": self.out_rate}
