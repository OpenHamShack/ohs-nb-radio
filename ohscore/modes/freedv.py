"""FreeDV voice, bound to the installed libcodec2 with ctypes.

Debian's codec2 package ships the library and the command-line tools but no
freedv_tx/freedv_rx binaries and, critically, no freedv_api.h -- there is
nothing to link against and nothing to tell us the struct layouts. Two
consequences shaped this module:

- Every function used here is a plain `(ptr, ints/floats) -> int` call,
  found by name with `nm -D` and typed by hand from the public API's
  documented signatures. Nothing here touches struct MODEM_STATS (the
  type freedv_get_modem_extended_stats() fills in): its layout is a
  dozen-odd fields, some of them 2D float arrays, and guessing it wrong
  from memory risks ctypes reading or writing past the real struct's
  end -- a corrupt read at best, a segfault at worst. SNR comes instead
  from freedv_get_modem_stats(f, int *sync, float *snr_est) -- confirmed
  from the real freedv_api.h at the 1.2.0 tag (fetched with curl from
  raw.githubusercontent.com/drowe67/codec2/1.2.0/src/freedv_api.h, since
  this host has the library but not the header), which is exactly the
  simpler, struct-free getter the API itself offers alongside the
  struct-based one: two output pointers, no struct to get wrong.
  freedv_get_sync() (also used, for the plain sync flag without SNR when
  nothing has changed) is likewise a plain int return, documented stably
  across codec2 versions.
- Which modes exist has to be found out at runtime, not assumed from a
  version number. On this host's codec2 1.2.0, probing shows FREEDV_MODE_1600
  (0), 700C (6) and 700D (7) come up with sane speech/modem sample rates;
  2020 (8) opens as a working 16 kHz-speech mode; the probed slot for 700E
  (10) opens a non-null handle but reports a 0 Hz speech rate -- not a
  working mode, whatever the enum value turns out to mean in this build.
  availability.py's whole job (see AVAILABLE_MODES below) is running that
  probe once and caching it, exactly as DESIGN.md asks every optional
  feature to.

FreeDV's own audio is 8 kHz (16 kHz for 2020's speech side); this daemon is
12 kHz everywhere else, so both directions go through a small rational
resampler (resample(), 2:3 or 3:2, 3:4 for 2020's speech) built from a
windowed-sinc FIR -- scipy isn't guaranteed on a Pi install, and this is a
short enough filter that a direct convolution is not a bottleneck next to
what codec2 itself costs per frame.
"""

from __future__ import annotations

import ctypes
import math
import threading
from typing import Callable

import numpy as np

from .. import host, sdr

FS = 12_000.0

# Which libcodec2 is opened is the shared codec loader's answer (shack_sdr
# codecs, RADIO-SDR-PLAN §5), as every codec's is from Radio's SDR milestone
# 1: an explicit SHACK_CODEC_CODEC2, the app's codecs folder, the copy the
# Windows and Mac builds carry (libcodec2.dll from FreeDV-GUI's Windows
# release, with the liblpcnetfreedv.dll it links against for 2020; Brian,
# 22/10/2026: keep shipping it), then the system's - and only a file that
# passed the loader's probe in a child process, so a wrong-ABI library
# found somewhere can no longer take the program down here. The binding
# below is unchanged. Without shack_sdr (the .deb built for any machine)
# the old search stands in: the bundle first, then the system's.
_LIBNAME = sdr.codec_path("codec2") if sdr.available() else host.find_library("codec2")
_lib = None
if _LIBNAME:
    try:
        _lib = ctypes.CDLL(_LIBNAME)
        _lib.freedv_open.restype = ctypes.c_void_p
        _lib.freedv_open.argtypes = [ctypes.c_int]
        _lib.freedv_close.argtypes = [ctypes.c_void_p]
        _lib.freedv_close.restype = None
        _lib.freedv_nin.argtypes = [ctypes.c_void_p]
        _lib.freedv_nin.restype = ctypes.c_int
        _lib.freedv_rx.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_short), ctypes.POINTER(ctypes.c_short)]
        _lib.freedv_rx.restype = ctypes.c_int
        _lib.freedv_tx.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_short), ctypes.POINTER(ctypes.c_short)]
        _lib.freedv_tx.restype = None
        _lib.freedv_get_sync.argtypes = [ctypes.c_void_p]
        _lib.freedv_get_sync.restype = ctypes.c_int
        _lib.freedv_get_modem_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                                 ctypes.POINTER(ctypes.c_float)]
        _lib.freedv_get_modem_stats.restype = None
        _lib.freedv_get_speech_sample_rate.argtypes = [ctypes.c_void_p]
        _lib.freedv_get_speech_sample_rate.restype = ctypes.c_int
        _lib.freedv_get_modem_sample_rate.argtypes = [ctypes.c_void_p]
        _lib.freedv_get_modem_sample_rate.restype = ctypes.c_int
        _lib.freedv_get_n_speech_samples.argtypes = [ctypes.c_void_p]
        _lib.freedv_get_n_speech_samples.restype = ctypes.c_int
        _lib.freedv_get_n_max_modem_samples.argtypes = [ctypes.c_void_p]
        _lib.freedv_get_n_max_modem_samples.restype = ctypes.c_int
        _lib.freedv_get_n_nom_modem_samples.argtypes = [ctypes.c_void_p]
        _lib.freedv_get_n_nom_modem_samples.restype = ctypes.c_int
        _TXT_CB = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char)
        _lib.freedv_set_callback_txt.argtypes = [ctypes.c_void_p, _TXT_CB, ctypes.c_void_p, ctypes.c_void_p]
        _lib.freedv_set_callback_txt.restype = None
    except (OSError, AttributeError):
        _lib = None

# Enum values straight from freedv_api.h's #defines (no header on this host,
# so these are copied from the published API, not derived); which ones this
# particular libcodec2 build actually supports is found out by _probe_mode(),
# not assumed from this table.
_MODE_IDS = {"1600": 0, "700c": 6, "700d": 7, "2020": 8, "700e": 10}

_probe_lock = threading.Lock()
_probe_cache: dict[str, tuple[bool, str]] = {}

WHY_NO_LIBRARY = "Install codec2 for FreeDV (needs libcodec2)"


def available(mode: str) -> tuple[bool, str]:
    """(is_usable, why_not) for one FreeDV mode name, probed once (opens a
    real freedv handle and sanity-checks its reported sample rate) and
    cached -- exactly the "probe lazily, cache" DESIGN.md asks every
    optional feature to do, because the probe itself is cheap but not
    instant (codec2 builds LDPC/FFT tables on open)."""
    with _probe_lock:
        if mode in _probe_cache:
            return _probe_cache[mode]
        result = _probe_mode(mode)
        _probe_cache[mode] = result
        return result


def _probe_mode(mode: str) -> tuple[bool, str]:
    if _lib is None:
        return False, WHY_NO_LIBRARY
    mode_id = _MODE_IDS.get(mode)
    if mode_id is None:
        return False, f"Unknown FreeDV mode {mode!r}"
    h = _lib.freedv_open(mode_id)
    if not h:
        return False, f"This codec2 build does not have FreeDV {mode.upper()}"
    speech_sr = _lib.freedv_get_speech_sample_rate(h)
    if speech_sr <= 0:
        # Not closed, on purpose: a half-made handle is what codec2 hands
        # back for a mode it was built without, and closing one can crash
        # the process. codec2 1.2.0 built without LPCNet (the Mac build's,
        # 07/10/2026) returns such a handle for 2020, and freedv_close then
        # dies in ofdm_destroy - at import, before the window ever showed.
        # One leaked handle per such mode, once per process, is the price.
        return False, f"This codec2 build's FreeDV {mode.upper()} probed non-functional (0 Hz speech rate)"
    _lib.freedv_close(h)
    return True, ""


def resample(x: np.ndarray, up: int, down: int) -> np.ndarray:
    """Rational resampler: zero-stuff by `up`, low-pass at the tighter of
    the two Nyquist rates, decimate by `down`. A windowed-sinc FIR rather
    than scipy.signal.resample_poly, which isn't guaranteed to exist on a
    Raspberry Pi OS install (no scipy anywhere in this codebase, per
    DESIGN.md) -- and short enough (a few hundred taps) that direct
    convolution is nowhere near the cost of a FreeDV frame itself."""
    g = math.gcd(up, down)
    up, down = up // g, down // g
    if up == 1 and down == 1:
        return x.astype(np.float32)
    n = len(x)
    if n == 0:
        return x.astype(np.float32)
    up_sig = np.zeros(n * up, dtype=np.float64)
    up_sig[::up] = x
    taps = 32 * max(up, down) + 1
    t = np.arange(taps) - (taps - 1) / 2.0
    cutoff = 1.0 / max(up, down)
    h = np.sinc(cutoff * t) * cutoff * up  # *up compensates the energy lost to zero-stuffing
    h *= np.hamming(taps)
    out = np.convolve(up_sig, h, mode="same")[::down]
    return out.astype(np.float32)


def _float_to_pcm16(x: np.ndarray) -> np.ndarray:
    return np.clip(x * 32767.0, -32768, 32767).astype(np.int16)


def _pcm16_to_float(x: np.ndarray) -> np.ndarray:
    return (x.astype(np.float32) / 32768.0)


class Decoder:
    """FreeDV RX. feed() takes 12 kHz audio off the air; decoded speech
    (resampled back to 12 kHz) goes to `audio_out`, and sync/text events go
    to `emit` the same way every other mode's events do."""

    def __init__(self, emit: Callable[[dict], None], audio_out: Callable[[np.ndarray], None],
                 mode: str = "700d", **_opts):
        self.emit = emit
        self.audio_out = audio_out
        self.mode = mode
        ok, why = available(mode)
        if not ok:
            raise RuntimeError(why)
        self._h = _lib.freedv_open(_MODE_IDS[mode])
        self.modem_sr = _lib.freedv_get_modem_sample_rate(self._h)
        self.speech_sr = _lib.freedv_get_speech_sample_rate(self._h)
        self._text_chars: list[str] = []
        self._txt_cb = _TXT_CB(lambda state, c: self._text_chars.append(chr(c[0] if isinstance(c, bytes) else c)))
        _lib.freedv_set_callback_txt(self._h, self._txt_cb, None, None)
        self.reset()

    def reset(self) -> None:
        self._modem_buf = np.zeros(0, dtype=np.int16)
        self._last_sync = None
        self._last_snr = None

    def feed(self, audio: np.ndarray, t: float) -> None:
        # 12 kHz -> modem rate (8 kHz for every mode except 2400A/B, which
        # this module doesn't offer). down/up chosen from the measured rate
        # rather than hardcoded 3:2, so a future mode at a different modem
        # rate doesn't need a new code path here.
        modem_in = resample(audio.astype(np.float64), int(self.modem_sr), int(FS))
        self._modem_buf = np.concatenate([self._modem_buf, _float_to_pcm16(modem_in)])

        while True:
            nin = _lib.freedv_nin(self._h)
            if len(self._modem_buf) < nin:
                break
            frame = self._modem_buf[:nin]
            self._modem_buf = self._modem_buf[nin:]
            speech = (ctypes.c_short * _lib.freedv_get_n_speech_samples(self._h))()
            n_out = _lib.freedv_rx(self._h, speech,
                                    frame.ctypes.data_as(ctypes.POINTER(ctypes.c_short)))
            sync_c, snr_c = ctypes.c_int(), ctypes.c_float()
            _lib.freedv_get_modem_stats(self._h, ctypes.byref(sync_c), ctypes.byref(snr_c))
            sync, snr = bool(sync_c.value), round(float(snr_c.value), 1)
            # Emitted on every real change, not every frame: sync flips are
            # rare and always worth a toast-worthy event; SNR drifts
            # continuously once synced, so only report it when it's moved
            # enough to matter (0.1 dB, the same rounding used above) rather
            # than flooding the console with a new event every few ms.
            if sync != self._last_sync or (sync and snr != self._last_snr):
                self.emit({"mode": "freedv", "fdv_mode": self.mode, "sync": sync, "snr": snr})
                self._last_sync, self._last_snr = sync, snr
            if self._text_chars:
                self.emit({"mode": "freedv", "fdv_mode": self.mode, "text": "".join(self._text_chars)})
                self._text_chars.clear()
            if n_out > 0:
                speech_f = _pcm16_to_float(np.frombuffer(speech, dtype=np.int16, count=n_out))
                out12k = resample(speech_f.astype(np.float64), int(FS), int(self.speech_sr))
                self.audio_out(out12k.astype(np.float32))

    def close(self) -> None:
        if self._h:
            _lib.freedv_close(self._h)
            self._h = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class FreeDVTx:
    """FreeDV TX. Not render()-once like the text modes: FreeDV's own frame
    size doesn't divide evenly into whatever block size a caller happens to
    hand it (a mic callback has no reason to match freedv_get_n_speech_
    samples()), so process() buffers speech in and only calls freedv_tx
    once a full native-rate speech frame has accumulated, handing back
    whatever modem audio that produced -- which may be nothing, on a call
    that only topped up the buffer."""

    def __init__(self, mode: str = "700d", **_opts):
        self.mode = mode
        ok, why = available(mode)
        if not ok:
            raise RuntimeError(why)
        self._h = _lib.freedv_open(_MODE_IDS[mode])
        self.modem_sr = _lib.freedv_get_modem_sample_rate(self._h)
        self.speech_sr = _lib.freedv_get_speech_sample_rate(self._h)
        self._n_speech = _lib.freedv_get_n_speech_samples(self._h)
        self._n_modem = _lib.freedv_get_n_nom_modem_samples(self._h)
        self._speech_buf = np.zeros(0, dtype=np.int16)
        self._text = ""  # pulled one character at a time by the TX text callback

        def _tx_pull(state):
            if self._text:
                c = self._text[0]
                self._text = self._text[1:]
                return ord(c)
            return 0

        _TX_TXT_CB = ctypes.CFUNCTYPE(ctypes.c_char, ctypes.c_void_p)
        self._tx_cb = _TX_TXT_CB(lambda state: bytes([_tx_pull(state) & 0xFF]))
        _lib.freedv_set_callback_txt(self._h, ctypes.cast(None, _TXT_CB), self._tx_cb, None)

    def send_text(self, text: str) -> None:
        self._text += text

    def process(self, block: np.ndarray) -> np.ndarray:
        native = resample(block.astype(np.float64), int(self.speech_sr), int(FS))
        self._speech_buf = np.concatenate([self._speech_buf, _float_to_pcm16(native)])
        out_chunks = []
        while len(self._speech_buf) >= self._n_speech:
            speech_frame = self._speech_buf[:self._n_speech]
            self._speech_buf = self._speech_buf[self._n_speech:]
            modem = (ctypes.c_short * self._n_modem)()
            _lib.freedv_tx(self._h, modem, speech_frame.ctypes.data_as(ctypes.POINTER(ctypes.c_short)))
            modem_f = _pcm16_to_float(np.frombuffer(modem, dtype=np.int16, count=self._n_modem))
            out_chunks.append(resample(modem_f.astype(np.float64), int(FS), int(self.modem_sr)))
        if not out_chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(out_chunks).astype(np.float32)

    def close(self) -> None:
        if self._h:
            _lib.freedv_close(self._h)
            self._h = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
