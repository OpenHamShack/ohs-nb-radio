"""Audio in and out: PortAudio through pyaudio, or a null backend.

The engine's audio is 12 kHz mono float32 everywhere. This module is the only
place that knows the sound card's rate: it resamples on the engine side of
the ring buffers (in the RX and TX threads), so the PortAudio callbacks do
nothing but copy - a callback that computes is a callback that glitches when
the Pi is busy.

Receive playback keeps a small jitter buffer (~120 ms). On underrun the last
few milliseconds are faded out instead of stopping dead, and playback waits
for the buffer to refill to its target before resuming, so a hiccup is a
soft gap rather than a click and a stutter. The SDR's clock and the sound
card's are not the same crystal; if the buffer creeps past 240 ms the oldest
audio is dropped back to the target.

The microphone is opened only while something needs it - a voice over from
the sound card, a voice memory being recorded - through open_mic() and
close_mic(), never by start(). Until 0.1.10 start() opened it with the
speakers, so starting the radio asked for the microphone: on macOS that is a
permission prompt the moment the app opens, before its window, for someone
who may only ever listen (Brian, 10/10/2026, after the Radio dmg's install
proof showed no window). Opening it costs tens of milliseconds, taken before
the radio keys, and closing it afterwards turns off the system's "microphone
in use" light.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from . import host
from .dsp.resample import Resampler
from .i18n.text import _

log = logging.getLogger("ohsnb.audio")
RATE = 12_000


def _rms_db(x: np.ndarray) -> float:
    """RMS level of `x` in dBFS, floored well below the meter's range rather
    than at -inf for silence."""
    if not len(x):
        return -120.0
    return float(20 * np.log10(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-9))


class Ring:
    """Lock-protected circular float32 buffer; writes drop the oldest when full."""

    def __init__(self, size: int):
        self.buf = np.zeros(size, np.float32)
        self.size = size
        self.r = 0
        self.n = 0
        self.lock = threading.Lock()
        self.dropped = 0

    def write(self, x: np.ndarray):
        x = np.asarray(x, np.float32)
        with self.lock:
            if len(x) >= self.size:
                self.dropped += self.n + len(x) - self.size
                x = x[-self.size:]
                self.r, self.n = 0, 0
            over = self.n + len(x) - self.size
            if over > 0:
                self.r = (self.r + over) % self.size
                self.n -= over
                self.dropped += over
            w = (self.r + self.n) % self.size
            k = min(len(x), self.size - w)
            self.buf[w:w + k] = x[:k]
            self.buf[:len(x) - k] = x[k:]
            self.n += len(x)

    def read(self, n: int) -> np.ndarray:
        with self.lock:
            k = min(n, self.n)
            idx = (self.r + np.arange(k)) % self.size
            out = self.buf[idx]
            self.r = (self.r + k) % self.size
            self.n -= k
            return out

    def discard(self, n: int):
        with self.lock:
            k = min(n, self.n)
            self.r = (self.r + k) % self.size
            self.n -= k

    def __len__(self):
        return self.n


class TxOut:
    """One over's transmit audio to a sound device: what an external
    radio's modulator hears (an IC-9700's USB audio CODEC in USB-D, for NB's
    CAT PTT digital overs, 12/10/2026). Shaped like the part of an SDR
    device the engine's transmit loop and drain use - write() paces the
    loop by blocking while BUFFER seconds are already queued; tx_finish(),
    tx_queued() and tx_stop() - so a normal end drains it exactly as it
    drains a Pluto (Engine._tx_drain), and the last FT8 symbol is on air
    before the radio is unkeyed. `gain` is linear, applied here so the
    level the operator sets for the radio is never the speaker's.

    Opened for an over and closed after it, never at start-up, for the
    microphone's reason (module docstring): and an output left open
    between overs would put whatever reached it on the radio's modulator
    the next time anyone keyed it, by hand included."""

    BUFFER = 0.2
    underruns = 0       # times the card wanted audio mid-over and the ring had none (an over's log line)

    def write(self, audio: np.ndarray) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        """The device as the over's log line names it."""
        return repr(getattr(self, "device", "?"))

    def tx_finish(self) -> None:
        pass

    def tx_queued(self) -> float:
        return 0.0

    def tx_stop(self) -> None:
        pass


class NullTxOut(TxOut):
    """No sound card: the audio is kept (`chunks`, with the monotonic time
    each would start playing), and paced as a card would play it when
    realtime, so a test sees an over take as long as it would on air."""

    def __init__(self, device: str, gain: float, realtime: bool = True):
        self.device, self.gain, self.realtime = device, gain, realtime
        self.chunks: list[tuple[float, np.ndarray]] = []
        self.opened = time.monotonic()
        self.end = None              # when the queued audio will have played
        self.closed_at: float | None = None

    def write(self, audio):
        now = time.monotonic()
        start = max(now, self.end or now)
        a = np.asarray(audio, np.float32) * np.float32(self.gain)
        self.chunks.append((start, a))
        self.end = start + len(a) / RATE
        if self.realtime:
            wait = self.end - time.monotonic() - self.BUFFER
            if wait > 0:
                time.sleep(wait)

    def tx_queued(self) -> float:
        return max(0.0, (self.end or 0.0) - time.monotonic()) if self.realtime else 0.0

    def tx_stop(self):
        if self.closed_at is None:
            self.closed_at = time.monotonic()

    def describe(self) -> str:
        return f"{self.device!r} (no sound card)"

    def samples(self) -> np.ndarray:
        return np.concatenate([a for _, a in self.chunks]) if self.chunks else np.zeros(0, np.float32)

    def first_sound(self) -> float | None:
        """When the first non-silent chunk would start playing."""
        for t, a in self.chunks:
            if len(a) and float(np.max(np.abs(a))) > 1e-4:
                return t
        return None


class Backend:
    """Interface the engine uses. All audio arguments/results are 12 kHz."""

    name = "none"
    rate = RATE

    def start(self):
        pass

    def stop(self):
        pass

    def play(self, audio: np.ndarray):
        pass

    def monitor(self, audio: np.ndarray):
        pass

    def read_mic(self, n: int) -> np.ndarray:
        return np.zeros(n, np.float32)

    def open_mic(self) -> str:
        """Start hearing the microphone, for one user of it; pair with
        close_mic(). Returns '' or a sentence saying why there is none (the
        caller carries on with silence)."""
        return ""

    def close_mic(self):
        pass

    def mic_open(self) -> bool:
        return False

    def mic_level(self) -> float:
        return -120.0

    def open_tx_out(self, device: str, gain: float = 1.0) -> TxOut:
        """An output stream on the sound device named `device`, for one
        over (TxOut). Raises ValueError with a sentence when there is no
        such device: never the system default instead, which would play an
        FT8 signal through the speakers while the radio transmitted
        silence."""
        raise ValueError(_("No sound card: transmit audio cannot reach the radio"))

    def status(self) -> dict:
        return {"backend": self.name}


class NullAudio(Backend):
    """No sound card: playback is swallowed, the microphone is silence (or
    `source(n)` - tests feed SSB test audio through it). With realtime=True
    read_mic() takes as long as the audio it returns would have."""

    name = "null"

    def __init__(self, realtime: bool = True, source=None):
        self.realtime = realtime
        self.source = source
        self.played = 0
        self.t_next = None
        self.level = -120.0
        self.tx_outs: list[NullTxOut] = []

    def play(self, audio):
        self.played += len(audio)

    def read_mic(self, n: int) -> np.ndarray:
        if self.realtime:
            now = time.monotonic()
            if self.t_next is None or self.t_next < now - 0.5:
                self.t_next = now
            self.t_next += n / RATE
            wait = self.t_next - now - 0.05
            if wait > 0:
                time.sleep(wait)
        a = np.asarray(self.source(n), np.float32) if self.source else np.zeros(n, np.float32)
        self.level = 20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-9) if len(a) else -120.0
        return a

    def mic_level(self) -> float:
        return float(self.level)

    def open_tx_out(self, device: str, gain: float = 1.0) -> TxOut:
        # Tests name a device; "" is refused here as on a real card.
        if not device:
            raise ValueError(_("Choose the radio's sound device for transmit audio"))
        out = NullTxOut(device, gain, self.realtime)
        self.tx_outs.append(out)
        return out

    def status(self):
        return {"backend": "null", "played": self.played}


def _usable_api(pa, d: dict) -> bool:
    """Whether to offer a device. On Windows PortAudio lists every card once
    per host API (MME, DirectSound, WASAPI, WDM-KS), so a laptop's one
    headset shows up four times under near-identical names, and choosing by
    name - as Settings does, so a USB headset is found again on another
    port - would land on whichever came first anyway. Only the default host
    API is offered there: MME, which accepts any rate and mono float32 from
    every card, where WASAPI shared mode refuses anything but the mixer's own
    format. Linux has one host API in practice (ALSA) and keeps every
    device."""
    if not host.WINDOWS:
        return True
    try:
        return d["hostApi"] == pa.get_default_host_api_info()["index"]
    except (OSError, KeyError):
        return True


# Windows' MME API (the one offered there, _usable_api) cuts a device's
# name to 31 characters - MAXPNAMELEN, 32 with the terminating NUL - so
# "Microphone (Realtek(R) Audio)" survives but "Speakers (USB Audio CODEC
# Analog Stereo)" arrives as "Speakers (USB Audio CODEC Analo", brackets
# unbalanced (Windows test 17/10/2026, finding 2). WASAPI lists the same
# endpoints by their whole names.
MME_NAME_MAX = 31


def same_device(want: str, name: str) -> bool:
    """Whether the device listed as `name` is the one saved as `want`,
    ignoring case: the same name, or - where Windows' MME has cut the
    listed name at MME_NAME_MAX - `want` being the whole of it. A name
    saved before 17/10/2026 is MME's cut one, and still matches exactly."""
    w, n = want.strip().lower(), name.strip().lower()
    if not w or not n:
        return False
    return w == n or (len(name) == MME_NAME_MAX and w.startswith(n))


def display_name(name: str, cut: bool = False) -> str:
    """`name` fit to show: one that was cut (`cut`, or brackets left open)
    ends in an ellipsis and has its brackets closed - "Speakers (USB Audio
    CODEC Analo...)" rather than an open bracket that reads as a typing
    error."""
    opened = name.count("(") - name.count(")")
    if not cut and opened <= 0:
        return name
    return name.rstrip() + "\u2026" + ")" * max(0, opened)


def _whole_names(pa) -> dict[tuple[str, bool], str]:
    """{(MME's cut name lower-cased, is an input): WASAPI's whole name} on
    Windows, from WASAPI's own list; empty elsewhere or without WASAPI."""
    if not host.WINDOWS:
        return {}
    try:
        import pyaudio
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
    except (OSError, IOError, KeyError, AttributeError, ImportError):
        return {}
    out = {}
    for i in range(pa.get_device_count()):
        try:
            d = pa.get_device_info_by_index(i)
        except (OSError, IOError):
            continue
        if d.get("hostApi") != wasapi:
            continue
        name = str(d["name"])
        if len(name) <= MME_NAME_MAX:
            continue
        for is_in in (True, False):
            if d["maxInputChannels" if is_in else "maxOutputChannels"] > 0:
                out.setdefault((name[:MME_NAME_MAX].lower(), is_in), name)
    return out


def list_devices() -> list[dict]:
    """Sound devices PortAudio can see: [{index, name, full, label, inputs,
    outputs, rate}]. `name` is PortAudio's; `full` the whole name where
    Windows' MME cut it (else `name`), which Settings saves - same_device()
    finds the device by either; `label` the one to show (display_name)."""
    try:
        import pyaudio
    except ImportError:
        return []
    pa = pyaudio.PyAudio()
    try:
        whole = _whole_names(pa)
        out = []
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if not _usable_api(pa, d):
                continue
            name = str(d["name"])
            ins, outs = int(d["maxInputChannels"]), int(d["maxOutputChannels"])
            cut = host.WINDOWS and len(name) == MME_NAME_MAX
            full = whole.get((name.lower(), ins > 0), name) if cut else name
            out.append({"index": i, "name": name, "full": full,
                        "label": full if full != name else display_name(name, cut),
                        "inputs": ins, "outputs": outs, "rate": float(d["defaultSampleRate"])})
        return out
    finally:
        pa.terminate()


def _default_name(pa, output: bool) -> str | None:
    """The name of the device "System default" means right now, or None
    when there is none. Each system's default hides behind a different
    word: PortAudio's ALSA default on a Linux desktop is the sound server
    ("default", "pulse"), so the server is asked what is behind it, and
    shown as the server's word if it will not say; MME's default on
    Windows is "Microsoft Sound Mapper", which routes to Windows' default
    endpoint - the one WASAPI's default names. A Mac's CoreAudio default
    is already the device."""
    try:
        info = pa.get_default_output_device_info() if output else pa.get_default_input_device_info()
    except (OSError, IOError):
        return None
    name = str(info.get("name") or "")
    if not name:
        return None
    if not host.WINDOWS and not host.MACOS and name.lower() in host.SOUND_SERVER_ALIASES:
        return host.sound_server_default(output) or name
    if host.WINDOWS and name.lower().startswith("microsoft sound mapper"):
        try:
            import pyaudio
            api = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            idx = api["defaultOutputDevice" if output else "defaultInputDevice"]
            if idx >= 0:
                return str(pa.get_device_info_by_index(idx)["name"])
        except (OSError, IOError, KeyError, AttributeError):
            pass
    return name


def default_devices() -> dict:
    """What "System default" resolves to now: {"input": name or None,
    "output": name or None, "error": ""}, or with "error" saying why
    nothing could be asked (PortAudio missing or failing). Settings › Audio
    shows these beside its "System default" entries, so an operator can
    see which headset or speaker that means without leaving the program.
    A fresh PyAudio each call: PortAudio reads the device list when it
    starts, so only a new one sees a headset plugged in since."""
    try:
        import pyaudio
    except ImportError:
        return {"input": None, "output": None, "error": _("PortAudio (python3-pyaudio) is not installed")}
    try:
        pa = pyaudio.PyAudio()
    except Exception as e:  # noqa: BLE001 - PortAudio's start-up fails in more ways than OSError
        return {"input": None, "output": None, "error": _("PortAudio could not start ({error})").format(error=e)}
    try:
        return {"input": _default_name(pa, False), "output": _default_name(pa, True), "error": ""}
    finally:
        pa.terminate()


class PortAudio(Backend):
    name = "portaudio"
    TARGET = 0.12     # jitter buffer, seconds
    # Playback starts, and resumes after an underrun, once the ring holds
    # this much. It was half of TARGET until 17/10/2026, which is less than
    # one receive block (75 ms): resuming as the first block landed left
    # the ring running between empty and one block, with no cushion at all,
    # so after one hiccup ordinary block-to-block jitter underran again.
    # Simulated with 75 ms blocks and a 20 ms callback over a minute (tests/
    # test_audio_jitter.py): 2 underruns at 20-30 ms of jitter before, none
    # after. It costs 60 ms more delay after a gap, never in steady state.
    RESUME = TARGET
    MAX = 0.24        # beyond this the SDR clock has outrun the card's: drop back to TARGET

    def __init__(self, out_name: str = "", in_name: str = "", out2_name: str = ""):
        import pyaudio  # noqa: F401 - fail here, with ImportError, if missing
        self.out_name, self.in_name, self.out2_name = out_name, in_name, out2_name
        self.pa = None
        self.streams = []
        self.rate = None
        self.notes: list[str] = []
        self.priming = True
        self.underruns = 0
        self.level = -120.0
        self.last_sample = 0.0
        self.mic_left = np.zeros(0, np.float32)     # 12 kHz mic samples resampled but not yet read (read_mic)
        # The microphone's stream, opened by open_mic and closed when its
        # last user calls close_mic: recording and a voice over can overlap
        # for a moment (keying stops a recording, whose thread lets go of
        # the microphone after the transmit thread has taken it).
        self.mic_stream = None
        self.mic_users = 0
        self.mic_lock = threading.Lock()

    # -- device selection -------------------------------------------------------
    def _find(self, want: str, inputs: bool) -> int | None:
        if not want:
            return None
        key = "maxInputChannels" if inputs else "maxOutputChannels"
        w = want.lower()
        for i in range(self.pa.get_device_count()):
            d = self.pa.get_device_info_by_index(i)
            if d[key] > 0 and same_device(want, str(d["name"])) and _usable_api(self.pa, d):
                return i
        for i in range(self.pa.get_device_count()):
            d = self.pa.get_device_info_by_index(i)
            if d[key] > 0 and w in d["name"].lower() and _usable_api(self.pa, d):
                return i
        self.notes.append(f"Sound device {want!r} not found; using the system default")
        return None

    def _pick_rate(self, out_idx, in_idx) -> int:
        import pyaudio
        for r in (48_000, 44_100, 24_000, 96_000):
            try:
                ok = self.pa.is_format_supported(r, output_device=out_idx if out_idx is not None else
                                                 self.pa.get_default_output_device_info()["index"],
                                                 output_channels=1, output_format=pyaudio.paFloat32)
                if ok:
                    return r
            except (ValueError, OSError):
                continue
        try:
            return int(self.pa.get_default_output_device_info()["defaultSampleRate"])
        except (OSError, IOError):
            return 48_000

    def start(self):
        import pyaudio
        self.pa = pyaudio.PyAudio()
        out_idx = self._find(self.out_name, inputs=False)
        in_idx = self._find(self.in_name, inputs=True)
        self.rate = self._pick_rate(out_idx, in_idx)
        r = self.rate
        self.up = Resampler(r, RATE)          # 12 kHz -> card, RX thread
        self.mon_up = Resampler(r, RATE)      # 12 kHz -> card, TX thread (monitor)
        self.down = Resampler(RATE, r)        # card -> 12 kHz, TX thread
        self.play_ring = Ring(int(r * 1.0))
        self.mon_ring = Ring(int(r * 0.5))
        self.mic_ring = Ring(int(r * 1.0))
        self.fade = np.linspace(1, 0, max(1, int(r * 0.004)), dtype=np.float32)

        def out_cb(_in, frames, _ti, _st):
            # Copy only: everything heavy happened before the ring.
            need = frames
            if self.priming:
                if len(self.play_ring) >= int(self.RESUME * r):
                    self.priming = False
                out = np.zeros(need, np.float32)
            else:
                out = self.play_ring.read(need)
                if len(out) < need:
                    self.underruns += 1
                    self.priming = True
                    tail = np.zeros(need - len(out), np.float32)
                    k = min(len(self.fade), len(tail))
                    tail[:k] = self.last_sample * self.fade[:k]
                    out = np.concatenate([out, tail])
            if len(self.mon_ring):
                m = self.mon_ring.read(need)
                out[:len(m)] += m
            if len(out):
                self.last_sample = float(out[-1])
            return out.astype(np.float32).tobytes(), pyaudio.paContinue

        def in_cb(data, frames, _ti, _st):
            self._on_mic(np.frombuffer(data, np.float32))
            return None, pyaudio.paContinue

        kw = dict(format=pyaudio.paFloat32, channels=1, rate=r, frames_per_buffer=int(r * 0.02))
        self.streams.append(self.pa.open(output=True, output_device_index=out_idx, stream_callback=out_cb, **kw))
        # Not opened here: open_mic() does, with what it needs kept.
        self.in_idx, self.in_kw, self.in_cb = in_idx, kw, in_cb
        if self.out2_name:
            idx2 = self._find(self.out2_name, inputs=False)
            if idx2 is not None:
                self.out2_ring = Ring(int(r * 1.0))

                def out2_cb(_in, frames, _ti, _st):
                    o = self.out2_ring.read(frames)
                    if len(o) < frames:
                        o = np.concatenate([o, np.zeros(frames - len(o), np.float32)])
                    return o.tobytes(), pyaudio.paContinue

                self.streams.append(self.pa.open(output=True, output_device_index=idx2, stream_callback=out2_cb, **kw))
        for s in self.streams:
            s.start_stream()

    def stop(self):
        with self.mic_lock:
            self.mic_users = 0
            self._close_mic_stream()
        for s in self.streams:
            try:
                s.stop_stream()
                s.close()
            except OSError:
                pass
        self.streams = []
        if self.pa:
            self.pa.terminate()
            self.pa = None

    def open_mic(self) -> str:
        """The microphone's input stream, opened for the first user and
        shared by the rest. A card that will not open is a sentence, not an
        exception: the over goes out silent, as it always did without a
        microphone. Each opening starts from an empty ring, so nothing heard
        last time is sent this time."""
        with self.mic_lock:
            self.mic_users += 1
            if self.mic_stream is not None or self.pa is None:
                return ""
            self.mic_ring = Ring(int(self.rate * 1.0))
            self.mic_left = np.zeros(0, np.float32)
            self.down = Resampler(RATE, self.rate)
            try:
                st = self.pa.open(input=True, input_device_index=self.in_idx, stream_callback=self.in_cb,
                                  **self.in_kw)
                st.start_stream()
            except (OSError, ValueError) as e:
                return f"No microphone ({e}); voice transmit will send silence"
            self.mic_stream = st
            return ""

    def close_mic(self):
        with self.mic_lock:
            self.mic_users = max(0, self.mic_users - 1)
            if self.mic_users == 0:
                self._close_mic_stream()

    def _close_mic_stream(self):
        st, self.mic_stream = self.mic_stream, None
        if st is None:
            return
        try:
            st.stop_stream()
            st.close()
        except OSError:
            pass
        self.level = -120.0

    def mic_open(self) -> bool:
        return self.mic_stream is not None

    def _on_mic(self, chunk: np.ndarray):
        """Every raw chunk from the card, at the card's rate. Pulled out of
        the PortAudio callback so the "level keeps updating even when
        nothing is reading the ring" behaviour (read_mic() is only called by
        the TX thread, while keyed) can be driven directly in a test rather
        than needing a real stream open."""
        self.mic_ring.write(chunk)
        self.level = _rms_db(chunk)

    def play(self, audio):
        y = self.up(audio)
        self.play_ring.write(y)
        if len(self.play_ring) > self.MAX * self.rate:
            self.play_ring.discard(len(self.play_ring) - int(self.TARGET * self.rate))
        if hasattr(self, "out2_ring"):
            self.out2_ring.write(y)

    def monitor(self, audio):
        self.mon_ring.write(self.mon_up(audio))

    def read_mic(self, n: int) -> np.ndarray:
        """n samples at 12 kHz. Waits (at most the audio's own duration plus
        a little) for the card; whatever is missing is padded with silence so
        the transmitter is never starved.

        The few card samples read beyond n's worth (the +4: the resampler's
        phase means n outputs can need one input more than n x ratio) come
        out as an extra 12 kHz sample or two, which are kept for the next
        call. They used to be cut off with y[:n]: one sample thrown away
        every 75 ms block, a phase jump at 13 Hz that put about 10 %
        distortion (THD+N -20 dB at 48 kHz, -18 dB at 44.1 kHz on a 1 kHz
        tone) on every voice mode's transmitted audio - Ray's "strong
        signal, terrible audio" on 70 cm AM, 05/10/2026. The RF chain after
        this measured better than -100 dB, so this was the whole fault in
        software."""
        left = self.mic_left
        need = max(0, int(np.ceil((n - len(left)) * self.rate / RATE)) + 4) if len(left) < n else 0
        deadline = time.monotonic() + n / RATE + 0.1
        while len(self.mic_ring) < need and time.monotonic() < deadline:
            time.sleep(0.005)
        # Clock drift: never let the mic backlog grow past 200 ms.
        excess = len(self.mic_ring) - need - int(0.2 * self.rate)
        if excess > 0:
            self.mic_ring.discard(excess)
        raw = self.mic_ring.read(need) if need else np.zeros(0, np.float32)
        y = np.concatenate([left, self.down(raw)]) if need else left
        if len(y) < n:
            y = np.concatenate([y, np.zeros(n - len(y), np.float32)])
        y, self.mic_left = y[:n], y[n:]
        self.level = _rms_db(y)
        return y

    def mic_level(self) -> float:
        return float(self.level)

    def open_tx_out(self, device: str, gain: float = 1.0) -> TxOut:
        if not device:
            raise ValueError(_("Choose the radio's sound device for transmit audio"))
        if self.pa is None:
            raise ValueError(_("The sound system is not running"))
        idx = None
        for exact in (True, False):
            for i in range(self.pa.get_device_count()):
                d = self.pa.get_device_info_by_index(i)
                name = str(d["name"])
                hit = same_device(device, name) if exact else device.lower() in name.lower()
                if d["maxOutputChannels"] > 0 and hit and _usable_api(self.pa, d):
                    idx = i
                    break
            if idx is not None:
                break
        if idx is None:
            log.warning("TX audio out %r: no such output device (outputs: %s)", device,
                        ", ".join(repr(d) for d in self._output_names()) or "none")
            raise ValueError(_("The sound device {device} is not connected: transmit audio cannot reach the "
                               "radio").format(device=device))
        try:
            out = PortAudioTxOut(self.pa, idx, gain)
        except (OSError, ValueError) as e:
            log.warning("TX audio out %r (device %d) would not open: %s", device, idx, e)
            raise ValueError(_("The sound device {device} would not open ({error})").format(
                device=device, error=e)) from None
        # Once per over, at INFO: which card, through which host API, at
        # what rate and buffer - the first things to ask when the radio
        # hears nothing or hears it broken up.
        log.info("TX audio out opened: %s", out.describe())
        return out

    def _output_names(self) -> list[str]:
        names = []
        try:
            for i in range(self.pa.get_device_count()):
                d = self.pa.get_device_info_by_index(i)
                if d["maxOutputChannels"] > 0:
                    names.append(str(d["name"]))
        except (OSError, ValueError):
            pass
        return names

    def status(self):
        return {"backend": "portaudio", "rate": self.rate, "notes": list(self.notes), "underruns": self.underruns,
                "bufferMs": round(1000 * len(self.play_ring) / self.rate, 1) if self.rate else 0}


class PortAudioTxOut(TxOut):
    """TxOut on a PortAudio output: the callback only copies from a ring
    (as the speaker's does), the resampling happens in write(), on the
    transmit thread."""

    def __init__(self, pa, idx: int, gain: float):
        import pyaudio
        self.gain = float(gain)
        rate = None
        for r in (48_000, 44_100, 24_000, 96_000):
            try:
                if pa.is_format_supported(r, output_device=idx, output_channels=1, output_format=pyaudio.paFloat32):
                    rate = r
                    break
            except (ValueError, OSError):
                continue
        self.rate = rate or int(pa.get_device_info_by_index(idx)["defaultSampleRate"])
        self.up = Resampler(self.rate, RATE)
        self.ring = Ring(int(self.rate * 2.0))
        self.empty_at: float | None = None
        info = pa.get_device_info_by_index(idx)
        self.device = str(info.get("name", idx))
        try:
            self.host_api = str(pa.get_host_api_info_by_index(info["hostApi"])["name"])
        except (OSError, ValueError, KeyError, TypeError):
            self.host_api = "?"
        self.frames = int(self.rate * 0.02)
        # An underrun is the card asking for audio mid-over while the ring
        # is empty - a gap the radio transmits as silence. Before the first
        # write and once the over is draining an empty ring is expected.
        self.started = self.finishing = False
        self.underruns = 0

        def cb(_in, frames, _ti, _st):
            o = self.ring.read(frames)
            if len(o) < frames:
                if self.started and not self.finishing:
                    self.underruns += 1
                o = np.concatenate([o, np.zeros(frames - len(o), np.float32)])
            return o.tobytes(), pyaudio.paContinue

        self.stream = pa.open(output=True, output_device_index=idx, format=pyaudio.paFloat32, channels=1,
                              rate=self.rate, frames_per_buffer=self.frames, stream_callback=cb)
        self.stream.start_stream()
        try:
            self.latency = float(self.stream.get_output_latency())
        except (OSError, AttributeError):
            self.latency = 0.05

    def describe(self) -> str:
        return (f"{self.device!r} ({self.host_api}, {self.rate} Hz, buffer {1000 * self.frames / self.rate:.0f} ms, "
                f"latency {1000 * self.latency:.0f} ms)")

    def tx_finish(self) -> None:
        self.finishing = True

    def write(self, audio):
        self.ring.write(self.up(np.asarray(audio, np.float32) * np.float32(self.gain)))
        self.started = True
        deadline = time.monotonic() + 2.0
        while len(self.ring) > self.BUFFER * self.rate and time.monotonic() < deadline:
            time.sleep(0.005)

    def tx_queued(self) -> float:
        # What the ring holds, plus the card's own buffer, which the ring
        # cannot see: until that has played the radio is still modulating.
        left = len(self.ring) / self.rate
        if left > 0:
            self.empty_at = None
            return left + self.latency
        if self.empty_at is None:
            self.empty_at = time.monotonic()
        return max(0.0, self.empty_at + self.latency - time.monotonic())

    def tx_stop(self):
        st, self.stream = self.stream, None
        if st is None:
            return
        try:
            st.stop_stream()
            st.close()
        except OSError:
            pass


def make_backend(cfg: dict, realtime: bool = True) -> tuple[Backend, str]:
    """The configured backend, falling back to null (with the reason) when
    PortAudio or the card is unavailable: no sound card must never stop the
    radio."""
    if cfg.get("audioBackend", "portaudio") == "null":
        return NullAudio(realtime=realtime), ""
    try:
        b = PortAudio(cfg.get("audioOut", ""), cfg.get("audioIn", ""), cfg.get("audioOut2", ""))
        b.start()
        return b, "; ".join(b.notes)
    except ImportError:
        return NullAudio(realtime=realtime), "No audio: install python3-pyaudio"
    except Exception as e:  # noqa: BLE001 - any PortAudio failure degrades to silence
        log.warning("audio unavailable: %s", e)
        from . import diag
        diag.notable("audio-failed", str(e))
        return NullAudio(realtime=realtime), f"No audio ({e}); running without a sound card"
