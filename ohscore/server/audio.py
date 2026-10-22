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
signed little-endian, mono, ohscore.audio.RATE (12 kHz), both directions.

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
FORMAT = {"encoding": "s16le", "rate": RATE, "channels": 1}
# A listener a quarter of a second behind loses blocks rather than delay
# everyone: receive audio is live, not a recording.
LISTENER_BLOCKS = 32
MIC_SECONDS = 2.0


class StreamAudio(audio_mod.NullAudio):
    name = "stream"

    def __init__(self, realtime: bool = True):
        super().__init__(realtime=realtime)
        self._listeners: list[queue.Queue] = []
        self._taps: list = []
        self._lock = threading.Lock()
        self.mic = audio_mod.Ring(int(RATE * MIC_SECONDS))
        self.mic_writer = ""            # the client whose microphone this is

    # ---------------------------------------------------------- out
    def listen(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=LISTENER_BLOCKS)
        with self._lock:
            self._listeners.append(q)
        return q

    def unlisten(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def listeners(self) -> int:
        with self._lock:
            return len(self._listeners)

    def tap(self, fn):
        """Call `fn(pcm)` with every block played, on the engine's audio
        thread: it must only hand the block on (a recorder's push). Returns
        the function that removes it."""
        with self._lock:
            self._taps.append(fn)

        def untap():
            with self._lock:
                if fn in self._taps:
                    self._taps.remove(fn)
        return untap

    def play(self, audio):
        super().play(audio)
        with self._lock:
            qs, taps = list(self._listeners), list(self._taps)
        if not qs and not taps:
            return
        pcm = (np.clip(np.asarray(audio, np.float32), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        for fn in taps:
            fn(pcm)
        for q in qs:
            try:
                q.put_nowait(pcm)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(pcm)
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
        return {"backend": "stream", "played": self.played, "listeners": self.listeners()}
