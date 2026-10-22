"""Signal templates for the simulated transponder.

Everything is generated once, at 12 kHz complex baseband, as a loop the
simulator replays: per-block cost is then a slice, not synthesis. Templates
are analytic (one-sided) where a real transmitter would be SSB, so they sit
on the correct side of their dial frequency.
"""
from __future__ import annotations

import functools

import numpy as np

from ..dsp import morse
from ..dsp.fir import lowpass

RATE = 12_000.0


def analytic(audio: np.ndarray) -> np.ndarray:
    """Real audio -> its positive-frequency (USB) complex signal, same power
    split as an SSB transmitter's output: |z| follows the audio envelope."""
    n = len(audio)
    A = np.fft.fft(audio)
    A[n // 2 + 1:] = 0
    A[1:(n + 1) // 2] *= 2
    return np.fft.ifft(A).astype(np.complex64)


@functools.lru_cache(maxsize=None)
def fast_len(n: int) -> int:
    """The smallest length >= n whose only prime factors are 2, 3 and 5.

    numpy's FFT of a length with a large prime factor falls back to
    Bluestein's algorithm, tens of times slower than a nearby smooth length.
    Template lengths here are drawn at random, so most were such lengths:
    building one HF band's stations took 2.7 s on the development machine and 9 s on the
    Windows VM, nearly all of it in FFTs, and the band arrived that much
    late. At template sizes (10^5 samples and up) a smooth length is never
    more than about half a percent away."""
    n = max(1, int(n))
    best = 1 << (n - 1).bit_length()           # a power of two always qualifies
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            q = p35
            while q < n:
                q *= 2
            best = min(best, q)
            p35 *= 3
        p5 *= 5
    return best


def _fft_filter(x: np.ndarray, H) -> np.ndarray:
    # Zero-padded to a fast length (fast_len), so the formant ringing at the
    # end is cut off instead of wrapping onto the start. voice() windows
    # each syllable to silence at both ends afterwards, so the difference
    # is inaudible, and the pad costs far less than an awkward length.
    m = len(x)
    nf = fast_len(m)
    X = np.fft.rfft(x, nf)
    f = np.fft.rfftfreq(nf, 1 / RATE)
    return np.fft.irfft(X * H(f), nf)[:m]


def voice(rng: np.random.Generator, seconds: float, talk: tuple[float, float] = (0.0, 1.0)) -> np.ndarray:
    """Speech-like audio: a jittered glottal pulse train plus breath noise
    through two moving formants, chopped into syllables (~4 per second) with
    pauses between phrases; band-limited to 300-2700 Hz like a transmitter.
    Silent outside the `talk` fraction of the loop, so two templates offset
    by half a loop make a QSO.

    The loop is rounded up to a fast FFT length (fast_len) rather than cut
    at exactly `seconds`: the template is a loop, so analytic() must
    transform it whole - padding would break the seam - and nobody can hear
    a loop being a few milliseconds longer."""
    n = fast_len(int(seconds * RATE))
    out = np.zeros(n)
    f0 = rng.uniform(95, 180)
    t = 0
    edges = []
    while t < n:
        syl = int(rng.uniform(0.12, 0.32) * RATE)
        edges.append((t, min(n, t + syl)))
        t += syl + int(rng.uniform(0.02, 0.08) * RATE)
        if rng.random() < 0.12:
            t += int(rng.uniform(0.3, 0.9) * RATE)        # breath between phrases
    for a, b in edges:
        m = b - a
        if m < 32:
            continue
        pitch = f0 * (1 + 0.15 * rng.standard_normal()) * (1 + np.linspace(0, rng.uniform(-0.2, 0.2), m))
        phase = np.cumsum(pitch / RATE)
        pulses = (np.diff(np.floor(phase), prepend=np.floor(phase[0])) > 0).astype(float)
        exc = pulses * 8.0 + rng.standard_normal(m) * (0.3 if rng.random() < 0.8 else 2.0)
        F1, F2 = rng.uniform(300, 900), rng.uniform(900, 2400)

        def shape(f, F1=F1, F2=F2):
            return (1 / (1 + ((f - F1) / 120) ** 2) + 0.6 / (1 + ((f - F2) / 200) ** 2)) * ((f > 300) & (f < 2700))

        seg = _fft_filter(exc, shape)
        env = np.sin(np.linspace(0, np.pi, m)) ** 0.7
        out[a:b] = seg * env
    lo, hi = int(talk[0] * n), int(talk[1] * n)
    gate = np.zeros(n)
    gate[lo:hi] = 1.0
    out *= gate
    rms = np.sqrt(np.mean(out[lo:hi] ** 2)) + 1e-12
    out = out / rms * 0.25
    out = np.clip(out, -1, 1)         # the transmitter's own limiter
    return analytic(out)


def sustained_voice(rng: np.random.Generator, seconds: float) -> np.ndarray:
    """Speech at its most line-like: long vowels at a steady pitch, sharp
    formants, barely a pause - someone drawing out a call. voice() above
    jitters its pitch syllable to syllable the way conversation does,
    which never makes a line when squared; this does. It is the signal
    that took QO-100 NB's beacon lock off the middle beacon on air
    (05/10/2026), kept here so the tests can put it next to the beacon.
    Same level and band limits as voice(); talking all the time."""
    n = fast_len(int(seconds * RATE))
    out = np.zeros(n)
    f0 = rng.uniform(95, 180)
    t = 0
    while t < n:
        m = min(int(rng.uniform(0.25, 0.7) * RATE), n - t)
        if m < 64:
            break
        # A slow random walk of 0.3 % in pitch across the vowel.
        pitch = f0 * (1 + 0.05 * rng.standard_normal()) * (1 + 0.003 * rng.standard_normal(m).cumsum() / np.sqrt(m))
        phase = np.cumsum(pitch / RATE)
        pulses = (np.diff(np.floor(phase), prepend=np.floor(phase[0])) > 0).astype(float)
        exc = pulses * 8.0 + rng.standard_normal(m) * 0.2
        F1, F2 = rng.uniform(300, 900), rng.uniform(900, 2400)

        def shape(f, F1=F1, F2=F2):
            return (1 / (1 + ((f - F1) / 80) ** 2) + 0.6 / (1 + ((f - F2) / 150) ** 2)) * ((f > 300) & (f < 2700))

        out[t:t + m] = _fft_filter(exc, shape) * np.sin(np.linspace(0, np.pi, m)) ** 0.3
        t += m + int(rng.uniform(0.03, 0.1) * RATE)
    out = np.clip(out / (np.sqrt(np.mean(out ** 2)) + 1e-12) * 0.25, -1, 1)
    return analytic(out)


def keyed_carrier(env: np.ndarray) -> np.ndarray:
    return env.astype(np.complex64)


def cw_station(rng: np.random.Generator, text: str, wpm: float, seconds: float, talk=(0.0, 1.0)) -> np.ndarray:
    n = int(seconds * RATE)
    e = morse.envelope(text, wpm, RATE, tail=0.5)
    reps = int(np.ceil(n / max(len(e), 1)))
    e = np.tile(e, reps)[:n]
    lo, hi = int(talk[0] * n), int(talk[1] * n)
    gate = np.zeros(n, np.float32)
    gate[lo:hi] = 1
    return keyed_carrier(e * gate)


# QO-100's lower beacon (DK0SB, 10489.500 MHz) as it is on air, measured
# from Brian's recording of 07/10/2026 12:59 UTC (qo100-nb-2026-10-07-
# after-dish, both F1A tones decoded together, eight cycles in 5 min, all
# alike): this text at 12 WPM (a 100 ms dit, to the 5 ms frame), a word
# space, 12.0 s of key-down (the mark tone alone), 1.3 s of key-up, and
# round again - a cycle of 37.9 s. AMSAT-DL's band plan gives only "CW F1A
# 400Hz shift"; the text and speed are from the recording. The "two tones
# of several seconds at the end of each transmission" that DJ0ABR locks a
# PLL to (destevez.net, "Measuring QO-100 beacons frequency", 2019) are
# the key-down and the key-up after it.
BEACON_TEXT = "HI DE QO100 QRA DK0SB"
BEACON_WPM = 12.0
BEACON_CARRIER_S = 12.0
BEACON_GAP_S = 1.3


def f1a_beacon(text: str, wpm: float, shift: float = 400.0, mark_high: bool = True,
               carrier: float = 0.0, tail: float = 3.0) -> np.ndarray:
    """Constant-carrier FSK keyed by Morse: the space tone at 0 Hz, the mark
    `shift` Hz above (or below). The phase is continuous - the beacon is a
    single oscillator being pulled, not two switched. `carrier` seconds of
    key-down follow the text after a word space (the lower beacon's 12 s),
    then `tail` seconds of key-up."""
    if carrier:
        dit = 1.2 / wpm
        r = morse.runs(text, wpm) + [(0, 7 * dit), (1, carrier), (0, tail)]
        env = morse.envelope_of(r, RATE)
    else:
        env = morse.envelope(text, wpm, RATE, tail=tail)
    f = env * (shift if mark_high else -shift)
    ph = 2 * np.pi * np.cumsum(f) / RATE
    z = np.exp(1j * ph)
    # Close the loop smoothly: the tail is key-up, so the template ends on the
    # space tone; trim to a whole number of space-tone cycles (0 Hz: any).
    return z.astype(np.complex64)


def _bits_from_bytes(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, np.uint8)).astype(np.int8)


def bpsk_beacon(rng: np.random.Generator, seconds: float, baud: float = 400.0) -> np.ndarray:
    """AO-40-format beacon: frames of sync 39 15 ED 30 + 512 bytes + CRC,
    differentially encoded, Manchester (XOR with the bit clock), lowpassed
    at 560 Hz, balanced-modulated: BPSK with no residual carrier."""
    nbits = int(seconds * baud)
    data = bytearray()
    while len(data) * 8 < nbits:
        data += bytes([0x39, 0x15, 0xED, 0x30]) + rng.integers(0, 256, 514, dtype=np.uint8).tobytes()
    bits = _bits_from_bytes(bytes(data))[:nbits]
    diff = np.bitwise_xor.accumulate(bits)                       # differential encoding
    sym = np.repeat(diff * 2 - 1, 2) * np.tile([1, -1], nbits)    # Manchester: two half-bits
    spb = RATE / (2 * baud)                                       # samples per half-bit (15)
    x = np.repeat(sym.astype(float), int(round(spb)))
    h = lowpass(560.0, RATE, 129)
    y = np.convolve(x, h, mode="same")
    return (y / np.sqrt(np.mean(y ** 2))).astype(np.complex64)


def apsk_beacon(rng: np.random.Generator, seconds: float, baud: float = 2400.0) -> np.ndarray:
    """Stand-in for the 8APSK multimedia beacon: random 8-ary PSK at 2400 Bd,
    shaped to ~2.7 kHz. Looks right on a scope; nobody decodes it. NB's
    simulator sends a real HSmodem beacon instead where ohsdigi is built
    (ohsnb/devices/mmbeacon.py) and falls back to this."""
    n = int(seconds * RATE)
    nsym = int(seconds * baud) + 1
    s = np.exp(2j * np.pi * rng.integers(0, 8, nsym) / 8)
    t = np.arange(n) * baud / RATE
    x = s[np.minimum(t.astype(int), nsym - 1)]
    h = lowpass(1350.0, RATE, 101)
    y = np.convolve(x, h, mode="same")
    return (y / np.sqrt(np.mean(np.abs(y) ** 2))).astype(np.complex64)


def fsk_tones(rng: np.random.Generator, seconds: float, baud: float, shift: float, centre: float,
              duty=(0.0, 1.0)) -> np.ndarray:
    """RTTY-like: random bits as continuous-phase two-tone FSK around `centre`
    audio Hz (USB), active for the `duty` fraction of the loop."""
    n = int(seconds * RATE)
    nb = int(seconds * baud) + 1
    bits = rng.integers(0, 2, nb)
    idx = np.minimum((np.arange(n) * baud / RATE).astype(int), nb - 1)
    f = centre + (bits[idx] - 0.5) * shift
    z = np.exp(2j * np.pi * np.cumsum(f) / RATE)
    gate = np.zeros(n)
    gate[int(duty[0] * n):int(duty[1] * n)] = 1
    return (z * gate).astype(np.complex64)


def rtty_text(text: str, seconds: float, baud: float = 45.45, shift: float = 170.0, centre: float = 1500.0,
              gap: float = 4.0) -> np.ndarray:
    """An RTTY station sending `text` over and over, `gap` seconds of
    silence between overs, for `seconds`: ITA2 framed exactly as our own
    encoder sends it (modes/rtty.py: two LTRS first, 1.5 stop bits, mark
    high), as continuous-phase FSK at `centre` audio Hz (USB). Unlike
    fsk_tones' random bits it decodes, so the simulated band has RTTY a
    decoder can be checked against (Radio's Decoders view, its RTTY mode)."""
    from ..modes import rtty
    codes = [rtty.LTRS] * rtty.Encoder.LEAD_LTRS + rtty._text_to_codes(text)
    mark, space = centre + shift / 2, centre - shift / 2
    bit = 1.0 / baud
    segs = [(mark, 0.3)]                                  # (Hz, seconds): idle mark first
    for c in codes:
        segs.append((space, bit))                         # start bit
        segs += [(mark if b == "1" else space, bit) for b in c]
        segs.append((mark, 1.5 * bit))                    # stop bits
    segs.append((mark, 2 * bit))
    over = []
    t = 0.0
    pos = 0
    for f, dur in segs:
        t += dur
        end = int(round(t * RATE))
        over.append(np.full(end - pos, f))
        pos = end
    freq = np.concatenate(over)
    on = np.ones(len(freq))
    freq = np.concatenate([freq, np.full(int(gap * RATE), mark)])
    on = np.concatenate([on, np.zeros(int(gap * RATE))])
    n = int(seconds * RATE)
    reps = int(np.ceil(n / len(freq)))
    freq, on = np.tile(freq, reps)[:n], np.tile(on, reps)[:n]
    z = np.exp(2j * np.pi * np.cumsum(freq) / RATE)
    return (z * on).astype(np.complex64)


def psk_like(rng: np.random.Generator, seconds: float, baud: float, centre: float, duty=(0.0, 1.0)) -> np.ndarray:
    """PSK31-like: random phase reversals with the raised-cosine amplitude
    dips of real BPSK31, at `centre` audio Hz."""
    n = int(seconds * RATE)
    nb = int(seconds * baud) + 2
    rev = rng.random(nb) < 0.5
    sign = np.cumprod(np.where(rev, -1.0, 1.0))
    tb = np.arange(n) * baud / RATE
    k = np.minimum(tb.astype(int), nb - 2)
    frac = tb - k
    # Cosine-shaped transition between symbols k and k+1 (a dip through zero on a reversal).
    a = sign[k] * (0.5 + 0.5 * np.cos(np.pi * frac)) + sign[k + 1] * (0.5 - 0.5 * np.cos(np.pi * frac))
    z = a * np.exp(2j * np.pi * centre * np.arange(n) / RATE)
    gate = np.zeros(n)
    gate[int(duty[0] * n):int(duty[1] * n)] = 1
    return (z * gate).astype(np.complex64)


def ft8_like(rng: np.random.Generator, offset_hz: float) -> np.ndarray:
    """One 12.64 s FT8-shaped transmission (79 symbols, 6.25 Hz 8-GFSK at
    6.25 Bd) at `offset_hz` audio, used when ohscore.modes has no FT8 encoder.
    The Costas arrays are real; the payload symbols are random."""
    costas = [3, 1, 4, 0, 6, 5, 2]
    payload = rng.integers(0, 8, 58)
    syms = np.array(costas + list(payload[:29]) + costas + list(payload[29:]) + costas)
    sps = int(RATE * 0.16)
    f = np.repeat(syms * 6.25, sps).astype(float)
    # Smooth the frequency steps (GFSK-like): two passes of a running mean
    # over a quarter symbol, done with cumulative sums - O(n), unlike a long
    # np.convolve, because this runs at every 15 s slot.
    w = sps // 4
    for _ in range(2):
        c = np.cumsum(np.concatenate([np.full(w, f[0]), f, np.full(w, f[-1])]))
        f = (c[2 * w:] - c[:-2 * w])[: len(f)] / (2 * w)
    f = f + offset_hz
    z = np.exp(2j * np.pi * np.cumsum(f) / RATE)
    ramp = int(RATE * 0.02)
    env = np.ones(len(z))
    env[:ramp] = np.linspace(0, 1, ramp)
    env[-ramp:] = np.linspace(1, 0, ramp)
    return (z * env).astype(np.complex64)
