"""Settings' audio check: a live level from the chosen microphone and a test
tone to the chosen speaker, so the operator can pick the right device
*before* saving and restarting the radio.

For a candidate device the engine isn't already using, this opens its own
short-lived PortAudio stream - that way an operator can audition a device
(a USB headset on another port, say) before ever switching to it. But when
the candidate *is* the device the running engine already has open, a second
stream fails: PulseAudio/PipeWire would share it, but a bare ALSA device is
exclusive, and PortAudio reports that as "busy" - true of the attempt, not
of the device. For that one case the test rides the engine's own stream
instead of opening a second one: `audio.play()` queues the tone onto its
output ring exactly as a received signal would be, and `audio.mic_level()`
reads the level it measures from the mic, which the test opens for as long
as it runs (`open_mic`/`close_mic`: the engine does not keep it open). Callers pass the
engine's live `ohscore.audio.Backend` (or `None` when the radio isn't running)
as `engine_audio`.
"""
from __future__ import annotations

import math
import threading

import numpy as np

from .. import audio as audio_mod


def _find(pa, name: str, inputs: bool):
    if not name:
        return None
    best = None
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if (d["maxInputChannels"] if inputs else d["maxOutputChannels"]) <= 0:
            continue
        if not audio_mod._usable_api(pa, d):     # the same card once per host API on Windows
            continue
        if d["name"] == name:
            return i
        if best is None and name.lower() in d["name"].lower():
            best = i
    return best


class AudioTester:
    def __init__(self):
        self.pa = None
        self.stream = None
        self.level_db = -120.0
        self.lock = threading.Lock()
        self._live = None     # the engine's Backend, while riding its stream instead of our own

    def _pa(self):
        if self.pa is None:
            import pyaudio
            self.pa = pyaudio.PyAudio()
        return self.pa

    @staticmethod
    def _same_device(want: str, running: str | None) -> bool:
        """True if `want` names the device a running `PortAudio` backend
        already has open - compared as the configured strings (both "" is
        "system default"), which is what decides whether opening our own
        stream would hit the same exclusive ALSA device."""
        return running is not None and (want or "").strip().lower() == (running or "").strip().lower()

    def start_input(self, name: str, engine_audio=None) -> str:
        self.stop_input()
        if engine_audio is not None and engine_audio.name == "portaudio" and \
                self._same_device(name, getattr(engine_audio, "in_name", None)):
            # The engine opens its microphone only for whoever needs it
            # (ohscore/audio.py), and this check is one: held until
            # stop_input, as a voice over or a recording holds it.
            err = engine_audio.open_mic()
            if err:
                engine_audio.close_mic()
                return err
            self._live = engine_audio
            return ""
        try:
            import pyaudio
            pa = self._pa()
            idx = _find(pa, name, True)

            def cb(data, frames, _ti, _st):
                a = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(a * a) + 1e-12))
                with self.lock:
                    self.level_db = 20 * math.log10(rms + 1e-9)
                return (None, pyaudio.paContinue)

            self.stream = pa.open(format=pyaudio.paInt16, channels=1, rate=48000, input=True,
                                  input_device_index=idx, frames_per_buffer=1024, stream_callback=cb)
            self.stream.start_stream()
            return ""
        except ImportError:
            return "Audio needs python3-pyaudio."
        except Exception as e:  # noqa: BLE001 - any PortAudio failure becomes a sentence
            return f"Could not open the microphone: {e}"

    def level(self) -> float:
        if self._live is not None:
            return self._live.mic_level()
        with self.lock:
            return self.level_db

    def stop_input(self):
        live, self._live = self._live, None
        if live is not None:
            live.close_mic()
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:  # noqa: BLE001
                pass
            self.stream = None

    def tone(self, name: str, engine_audio=None, seconds: float = 1.2, hz: float = 700.0) -> str:
        if engine_audio is not None and engine_audio.name == "portaudio" and \
                self._same_device(name, getattr(engine_audio, "out_name", None)):
            t = np.arange(int(audio_mod.RATE * seconds)) / audio_mod.RATE
            env = np.minimum(1.0, np.minimum(t, seconds - t) / 0.02)
            x = (0.3 * env * np.sin(2 * np.pi * hz * t)).astype(np.float32)
            try:
                engine_audio.play(x)
                return ""
            except Exception as e:  # noqa: BLE001 - any backend failure becomes a sentence
                return f"Could not play to that device: {e}"
        try:
            import pyaudio
            pa = self._pa()
            idx = _find(pa, name, False)
            rate = 48000
            t = np.arange(int(rate * seconds)) / rate
            env = np.minimum(1.0, np.minimum(t, seconds - t) / 0.02)
            x = (0.3 * env * np.sin(2 * np.pi * hz * t) * 32767).astype(np.int16).tobytes()

            def play():
                try:
                    s = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, output=True,
                                output_device_index=idx)
                    s.write(x)
                    s.stop_stream()
                    s.close()
                except Exception:  # noqa: BLE001
                    pass

            threading.Thread(target=play, daemon=True, name="tone").start()
            return ""
        except ImportError:
            return "Audio needs python3-pyaudio."
        except Exception as e:  # noqa: BLE001
            return f"Could not play to that device: {e}"

    def close(self):
        self.stop_input()
        if self.pa is not None:
            try:
                self.pa.terminate()
            except Exception:  # noqa: BLE001
                pass
            self.pa = None
