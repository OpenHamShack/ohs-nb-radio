"""The voice keyer: recorded messages ("CQ CQ contest, this is ...") that
the operator sends with a key instead of saying them again.

Both apps have it, so it lives in the core. This module is the part that
is not the transmitter: the slots and their WAV files, recording a slot
from the microphone, playing one back to the speaker (which never keys),
and the CQ loop's clock. Sending is the engine's (Engine.send_voice), and
it goes through exactly the path PTT does - the same request, `_key`, the
app's `_tx_guard`, the same modulator with the operator's mic gain,
compressor and transmit filter - with the recording read where the
microphone would have been. That is deliberate: a second way to key with
its own checks is a second place for a guard to be missing (HAM's licence
and band plan, NB's beacon-level rule), and the recording is meant to
sound exactly like the operator saying it into the same chain.

What is stored is the raw microphone, before mic gain and the compressor,
so a memory recorded at one mic gain and sent at another changes level as
live speech would, and a WAV imported from elsewhere is treated as a
microphone too.

Files: <data>/keyer/voice-<n>.wav (12 kHz, mono, 16-bit - small, and
every audio program opens it), and <data>/keyer/voice.json with the
slots' names. Kept beside each other in the data folder rather than the
names in ui.json, so copying the folder to another machine keeps a
memory's name with its recording.

The CW memories are not here: they are the CW panel's macros, which
existed first (ohscore/ui/prefs.py "cwMacros", sent by the keyboard modes'
own queue at the keyer speed), and the F-keys send whichever the mode
has.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

from .dsp.resample import Resampler
from .i18n.text import _


log = logging.getLogger("ohscore.keyer")

RATE = 12_000
SLOTS = 6                 # F1 ... F6
# Longest memory kept, recorded or imported. A CQ is seconds; two minutes
# bounds the file and is still well inside the shortest transmit time-out
# an operator would set. Sending checks the time-out itself as well.
MAX_SECONDS = 120.0
# Shorter than this is a slip of the button, not a message: discarded.
MIN_SECONDS = 0.3
# Modes a voice memory can be sent in: the ones whose PTT sends the
# microphone through a voice chain. FreeDV included: its PTT feeds the mic
# to the codec, and so does a memory.
VOICE_MODES = ("usb", "lsb", "am", "fm", "freedv")


def read_wav(path: Path, max_seconds: float = MAX_SECONDS) -> np.ndarray:
    """A WAV file as 12 kHz mono float32. PCM of 8, 16, 24 or 32 bits at any
    rate; stereo is mixed to mono. Raises ValueError with a sentence."""
    try:
        with wave.open(str(path), "rb") as w:
            ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if n / max(1, rate) > max_seconds:
                raise ValueError(_("That recording is {seconds:.0f} s long; a voice memory can be at most "
                                   "{most:.0f} s").format(seconds=n / rate, most=max_seconds))
            raw = w.readframes(n)
    except wave.Error as e:
        # The wave module reads PCM only; a float WAV says "unknown format: 3".
        raise ValueError(_("Not a WAV file this program can read ({error}): save it as 16-bit PCM WAV").format(
            error=e)) from None
    except OSError as e:
        raise ValueError(_("Could not read {file}: {error}").format(file=Path(path).name, error=e.strerror or e)) from None
    if width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        x = v.astype(np.float32) / float(1 << 23)
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / float(1 << 31)
    else:
        raise ValueError(_("{bits}-bit WAV is not supported: save it as 16-bit PCM WAV").format(bits=width * 8))
    if ch > 1:
        x = x[:len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
    if rate != RATE:
        rs = Resampler(RATE, rate)
        # Flush the filter's tail with silence, so the end of the message
        # is not lost in its history.
        x = np.concatenate([rs(x), rs(np.zeros(64, np.float32))])
    return np.clip(x, -1.0, 1.0).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    """12 kHz mono 16-bit, written beside and renamed over the old one, so a
    failure part-way never leaves half a memory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(np.round(np.asarray(audio, np.float64) * 32768.0), -32768, 32767).astype("<i2")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".voice-", suffix=".wav")
    os.close(fd)
    try:
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm.tobytes())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _rms_db(x: np.ndarray) -> float:
    if not len(x):
        return -120.0
    return float(20 * np.log10(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-9))


class VoiceSlots:
    """The slots on disk. Not thread-safe by itself: Keyer holds its lock."""

    def __init__(self, folder: Path, n: int = SLOTS):
        self.folder = Path(folder)
        self.n = n
        self.names = [""] * n
        try:
            raw = json.loads((self.folder / "voice.json").read_text(encoding="utf-8"))
            for i, name in enumerate((raw or {}).get("names", [])[:n]):
                self.names[i] = str(name)[:24]
        except (OSError, ValueError, AttributeError):
            pass

    def path(self, i: int) -> Path:
        self._check(i)
        return self.folder / f"voice-{i + 1}.wav"

    def _check(self, i: int) -> None:
        if not 0 <= i < self.n:
            raise ValueError(_("There is no voice memory {number} (there are {count})").format(number=i + 1, count=self.n))

    def seconds(self, i: int) -> float:
        """The recording's length, 0.0 when the slot is empty."""
        try:
            with wave.open(str(self.path(i)), "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except (OSError, wave.Error, EOFError):
            return 0.0

    def name(self, i: int) -> str:
        self._check(i)
        return self.names[i]

    def label(self, i: int) -> str:
        """What a button or the transmit card calls it: its name, else "Memory n"."""
        return self.name(i) or f"Memory {i + 1}"

    def listing(self) -> list[dict]:
        return [{"slot": i, "name": self.names[i], "label": self.label(i), "seconds": round(self.seconds(i), 2)}
                for i in range(self.n)]

    def load(self, i: int) -> np.ndarray:
        if self.seconds(i) <= 0:
            raise ValueError(_("Voice memory {number} is empty: record it first (Radio › Voice memories…)").format(
                number=i + 1))
        return read_wav(self.path(i))

    def store(self, i: int, audio: np.ndarray) -> float:
        audio = np.asarray(audio, np.float32)
        secs = len(audio) / RATE
        if secs < MIN_SECONDS:
            raise ValueError(_("Nothing was recorded"))
        if secs > MAX_SECONDS + 0.5:
            raise ValueError(_("A voice memory can be at most {most:.0f} s").format(most=MAX_SECONDS))
        write_wav(self.path(i), audio)
        return secs

    def clear(self, i: int) -> None:
        try:
            self.path(i).unlink()
        except FileNotFoundError:
            pass

    def rename(self, i: int, name: str) -> None:
        self._check(i)
        self.names[i] = " ".join(str(name).split())[:24]
        self.folder.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=".voice-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"names": self.names}, f, indent=1)
        os.replace(tmp, self.folder / "voice.json")


class Keyer:
    """Recording, preview and the CQ loop, for one engine.

    Recording reads the engine's own microphone (`audio.read_mic`) and the
    preview writes to its monitor output, both on a thread of their own
    and only while the radio is not keyed: those two belong to the
    transmit thread while it runs. Keying stops either first
    (`yield_audio`, called by the engine's `_key`), so a PTT pressed in
    the middle of a recording takes the microphone, as it should.

    The loop: after a memory sent with repeat on ends normally, the next
    send is due `keyerRepeatSec` later; the engine's supervisor calls
    `tick`. Anything the operator does that means "I am answering" or
    "stop" ends it - any PTT, Escape/halt, a retune or mode change, an
    emergency unkey, a refusal - see Engine.send_voice and its callers.
    """

    BLOCK = 1200          # 100 ms of microphone per read

    def __init__(self, engine, folder: Path):
        self.engine = engine
        self.slots = VoiceSlots(folder)
        self.lock = threading.Lock()
        # Recording: the thread, its stop flag, the slot, what it has so far.
        self.rec_thread: threading.Thread | None = None
        self.rec_stop = threading.Event()
        self.rec_slot: int | None = None
        self.rec_chunks: list[np.ndarray] = []
        self.rec_level = -120.0
        self.rec_result: str = ""          # the last recording's outcome, a sentence
        # Preview.
        self.prev_thread: threading.Thread | None = None
        self.prev_stop = threading.Event()
        self.prev_slot: int | None = None
        # The loop: the slot repeating and when it is next due (None while
        # it is on the air or not armed).
        self.loop_slot: int | None = None
        self.loop_due: float | None = None
        self.loop_shown = None

    # ------------------------------------------------------------- recording
    def record(self, i: int, max_seconds: float = MAX_SECONDS) -> None:
        """Start recording slot i from the microphone; stop with `stop_recording`
        (or it stops by itself at `max_seconds`). Raises ValueError."""
        self.slots.path(i)
        e = self.engine
        if e.audio is None or not e.running:
            raise ValueError(_("Start the radio first: the recording comes from its microphone"))
        if e.st["keyed"]:
            raise ValueError(_("Not while transmitting"))
        self.stop_preview()
        self.stop_recording()
        with self.lock:
            self.rec_stop.clear()
            self.rec_slot, self.rec_chunks, self.rec_result = i, [], ""
            self.rec_thread = threading.Thread(target=self._record, args=(i, max_seconds),
                                               name=f"{e.THREAD_PREFIX}-keyer-rec", daemon=True)
            self.rec_thread.start()

    def _record(self, i: int, max_seconds: float) -> None:
        e = self.engine
        got = 0
        why = ""
        # The microphone is opened for the recording and let go after it
        # (ohscore/audio.py); a PTT meanwhile opens it for itself as well.
        mic = e.audio
        note = mic.open_mic()
        try:
            if note:
                # Silence saved as a memory would go out as a dead carrier.
                self.rec_result = f"Not recorded: {note}"
                return
            while not self.rec_stop.is_set() and got < max_seconds * RATE:
                if e.st["keyed"] or not e.running:
                    why = "the radio keyed" if e.st["keyed"] else "the radio stopped"
                    break
                a = np.asarray(e.audio.read_mic(self.BLOCK), np.float32)
                self.rec_chunks.append(a)
                self.rec_level = _rms_db(a)
                got += len(a)
            audio = np.concatenate(self.rec_chunks) if self.rec_chunks else np.zeros(0, np.float32)
            audio = audio[:int(max_seconds * RATE)]
            secs = self.slots.store(i, audio)
            self.rec_result = (f"Recorded {self.slots.label(i)}: {secs:.1f} s"
                               + (f" (stopped: {why})" if why else ""))
            log.info("voice memory %d recorded, %.1f s", i + 1, secs)
        except (ValueError, OSError) as ex:
            self.rec_result = f"Not recorded: {ex}"
        finally:
            mic.close_mic()
            self.rec_slot = None
            self.rec_level = -120.0

    def recording(self) -> dict | None:
        """{slot, seconds, level} while recording, else None."""
        i = self.rec_slot
        if i is None:
            return None
        return {"slot": i, "seconds": sum(len(c) for c in list(self.rec_chunks)) / RATE, "level": self.rec_level}

    def stop_recording(self) -> str:
        """Stop and save; returns what happened ('' when nothing was recording)."""
        t = self.rec_thread
        if t is None:
            return ""
        self.rec_stop.set()
        t.join(timeout=3)
        self.rec_thread = None
        return self.rec_result

    # ------------------------------------------------------------- preview
    def preview(self, i: int) -> float:
        """Play slot i to the speaker (the monitor output, mixed over receive).
        Never keys. Returns its length in seconds."""
        audio = self.slots.load(i)
        e = self.engine
        if e.audio is None or not e.running:
            raise ValueError(_("Start the radio first: the preview plays through its speaker"))
        if e.st["keyed"]:
            raise ValueError(_("Not while transmitting"))
        self.stop_preview()
        self.stop_recording()
        self.prev_stop.clear()
        self.prev_slot = i
        self.prev_thread = threading.Thread(target=self._preview, args=(audio,),
                                            name=f"{e.THREAD_PREFIX}-keyer-play", daemon=True)
        self.prev_thread.start()
        return len(audio) / RATE

    def _preview(self, audio: np.ndarray) -> None:
        e = self.engine
        t_next = time.monotonic()
        try:
            for pos in range(0, len(audio), self.BLOCK):
                if self.prev_stop.is_set() or e.st["keyed"] or not e.running:
                    return
                e.audio.monitor(audio[pos:pos + self.BLOCK] * np.float32(0.8))
                # Paced to real time, a block ahead: the monitor ring holds
                # half a second and drops the oldest when it is overfilled.
                t_next += self.BLOCK / RATE
                wait = t_next - time.monotonic() - self.BLOCK / RATE
                if wait > 0 and self.prev_stop.wait(wait):
                    return
        finally:
            self.prev_slot = None

    def previewing(self) -> int | None:
        return self.prev_slot

    def stop_preview(self) -> None:
        t = self.prev_thread
        if t is None:
            return
        self.prev_stop.set()
        t.join(timeout=2)
        self.prev_thread = None

    def yield_audio(self) -> None:
        """The transmitter is about to take the microphone and the monitor."""
        if self.rec_thread is not None and threading.current_thread() is not self.rec_thread:
            self.stop_recording()
        if self.prev_thread is not None and threading.current_thread() is not self.prev_thread:
            self.stop_preview()

    # ------------------------------------------------------------- the loop
    def arm(self, i: int | None) -> None:
        """A memory has just been keyed; i is the slot to repeat (None: once)."""
        with self.lock:
            self.loop_slot, self.loop_due = i, None
            self.loop_shown = None

    def looping(self) -> bool:
        return self.loop_slot is not None

    def cancel(self, reason: str = "") -> bool:
        """End the loop (if any). True if there was one."""
        with self.lock:
            was = self.loop_slot is not None
            self.loop_slot, self.loop_due, self.loop_shown = None, None, None
        if was:
            log.info("voice keyer loop cancelled%s", f": {reason}" if reason else "")
        return was

    def over_ended(self, finished: bool, interval: float) -> bool:
        """The memory's over has ended; `finished` if it was sent to the end
        (not halted or refused). True if the loop goes round again."""
        with self.lock:
            if self.loop_slot is None:
                return False
            if not finished:
                self.loop_slot = self.loop_due = None
                return False
            self.loop_due = time.monotonic() + max(0.0, interval)
            return True

    def due(self, now: float) -> tuple[int, float] | None:
        """(slot, seconds until due) while a repeat is waiting, else None."""
        with self.lock:
            if self.loop_slot is None or self.loop_due is None:
                return None
            return self.loop_slot, self.loop_due - now

    def claim(self, i: int, now: float) -> bool:
        """Take the due repeat of slot i, once: True for exactly one caller."""
        with self.lock:
            if self.loop_slot != i or self.loop_due is None or self.loop_due > now:
                return False
            self.loop_due = None
            return True

    def shutdown(self) -> None:
        self.cancel("the radio stopped")
        self.stop_preview()
        self.stop_recording()
