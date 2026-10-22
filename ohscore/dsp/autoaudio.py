"""Best audio: receive settings chosen from measurements of the station
being listened to.

One request listens to a few seconds of the receive channel (and counts
impulses on the wideband stream, which is where the noise blanker works),
measures, and chooses the receive filter, AGC speed, noise reduction and
noise blanker by plain rules - no model, nothing learnt - so every choice
comes with the measurement and the rule that made it, and the operator can
see why and disagree. It is applied once; nothing here keeps adjusting, so
whatever the operator sets afterwards stands.

What is measured, from the channel centred on the dial (audio terms: Hz
above the carrier for USB, below it for LSB):

- **SNR**: the station's speech against the noise, in the band it occupies.
  The noise is the channel's floor (ohscore/dsp/autotune.py's percentile
  over the whole channel); the speech is the 80th percentile of 43 ms
  frames' in-band power less that noise - speech comes in syllables, and
  the pauses between them would make a mean say how talkative the
  operator is rather than how loud.
- **Occupied band**: where the station's averaged spectrum stands over the
  noise (autotune.occupied), in audio hertz.
- **Impulses**: the noise blanker's own test (samples over nbThreshold
  times the wideband mean) counted per second over the capture, before
  any blanking.

The rules, and why:

- **Noise reduction** is for weak signals and only harms strong ones: on a
  clean signal NR2 has nothing to take away but the edges of the speech.
  Off at 20 dB and over; below, on, stronger the weaker the signal (30 %
  at 15 dB, 50 % at 10, 70 % at 5 and under) - each 10 % is 4 dB more off
  the noise (ohscore/dsp/nr.py).
- **Filter**: just wider than the speech heard - 50 Hz under its low edge,
  100 Hz over its high edge - since outside it there is only noise and
  neighbours. Never narrower than 300-2300 Hz's worth of speech, never
  wider than 100-2900. Weak signals lose the top first: under 10 dB the
  high edge stops at 2500 Hz, under 6 dB at 2300 - above that a weak
  voice's sibilants are under the noise anyway, and hiss is what is left.
- **AGC**: slow on a weak signal, so the gain holds through the pauses
  instead of lifting the noise between every word; medium on a strong
  one; fast when there are impulses the blanker will not catch all of,
  so a crash does not hold the gain down for a second. Fading (QSB) would
  argue for a faster AGC too, but four seconds cannot measure it: a test
  of one-second speech peaks read a 12 dB, 2-second fade no differently
  from the ordinary swing between one phrase and the next, so it was left
  out rather than guessed at.
- **Noise blanker** on when impulses come at 2 a second or more, else off
  (blanking also takes a bite out of the signal each time it fires).

Best audio sets all five every time, rather than only those a measurement
argues for: the result then depends on the signal alone, not on what was
set before, and the operator always sees one complete set to change.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .autotune import MIN_SWING_DB, _edge, level_swing, noise_floor, occupied, psd
from ..i18n.text import _

RATE = 12_000.0
FRAME = 512
CAPTURE_SECONDS = 4.0
NR_OFF_SNR = 20.0
IMPULSE_RATE = 2.0           # per second


@dataclass
class Measured:
    snr: float                    # dB, speech vs noise in the occupied band
    band: tuple[float, float]     # occupied, audio Hz
    impulses: float               # per second, on the wideband stream


@dataclass
class Choice:
    ok: bool
    why: str = ""                       # refusal
    settings: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)   # (setting, sentence)
    measured: Measured | None = None

    def summary(self) -> str:
        """One line for the status and the toast."""
        if not self.ok:
            return self.why
        m, s = self.measured, self.settings
        nr = f"NR {s['nrStrength']:.0f} %" if s["nr"] else "NR off"
        return (f"{m.snr:.0f} dB SNR, speech {m.band[0]:.0f}-{m.band[1]:.0f} Hz, {m.impulses:.1f} impulses/s: "
                f"filter {s['filterLo']:.0f}-{s['filterHi']:.0f} Hz, AGC {s['agc']}, {nr}, "
                f"NB {'on' if s['nb'] else 'off'}")


def measure(iq: np.ndarray, sideband: str, impulses: float, rate: float = RATE) -> Measured | None:
    """Measurements of the station on the dial; None when nothing in the
    voice passband stands above the noise."""
    x = np.asarray(iq, np.complex64)
    if sideband == "lsb":
        x = np.conj(x)          # audio is then the positive frequencies, as USB
    f, P = psd(x, rate)
    floor = noise_floor(P, f)
    segs = [(a, b) for a, b in occupied(f, P, floor) if b > 100.0 and a < 3500.0 and b - a >= 300.0]
    if not segs:
        return None
    # Everything from the lowest such run to the highest, bridged - a voice
    # with a quiet gap between formants is still one voice - and its two
    # edges placed where the speech itself starts (autotune's edge rule:
    # within 10 dB of the band's body), not where its faint skirt does: on
    # a strong signal the transmitter's limiter splatter and the syllable
    # envelope stand out of the noise hundreds of hertz beyond the voice.
    a0 = max(min(a for a, _ in segs), 0.0)
    b0 = min(max(b for _, b in segs), 4000.0)
    lo = max(_edge(f, P, floor, a0, b0, upper=False), 0.0)
    hi = min(_edge(f, P, floor, a0, b0, upper=True), 4000.0)
    if hi - lo < 300.0:
        return None
    n = len(x) // FRAME
    if n < 8:
        return None
    w = np.hanning(FRAME)
    S = np.abs(np.fft.fft(x[:n * FRAME].reshape(n, FRAME) * w, axis=1)) ** 2 / np.sum(w ** 2)
    fb = np.fft.fftfreq(FRAME, 1 / rate)
    band = (fb >= lo) & (fb <= hi)
    # Both spectra are scaled so white noise reads the same per bin
    # whatever the transform length: the band's noise is the floor per bin
    # times its bins.
    noise = floor * band.sum()
    pw = S[:, band].sum(axis=1)
    speech = max(float(np.percentile(pw, 80)) - noise, 1e-30)
    snr = 10 * np.log10(speech / noise)
    return Measured(snr=float(snr), band=(float(lo), float(hi)), impulses=float(impulses))


def _r50(v: float) -> float:
    return float(round(v / 50.0) * 50.0)


def choose(m: Measured) -> Choice:
    """The rules (module docstring) applied to measurements."""
    s, why = {}, []
    if m.snr >= NR_OFF_SNR:
        s["nr"], s["nrStrength"] = False, None
        why.append(("nr", f"off: {m.snr:.0f} dB is a strong signal, and NR would only take the edges off it"))
    else:
        strength = 30.0 if m.snr >= 12.5 else 50.0 if m.snr >= 7.5 else 70.0
        s["nr"], s["nrStrength"] = True, strength
        why.append(("nr", f"on at {strength:.0f} %: {m.snr:.0f} dB SNR (30 % from 12.5 dB, 50 % from 7.5, "
                          f"70 % below)"))
    lo = min(max(_r50(m.band[0] - 50.0), 100.0), 300.0)
    hi = min(max(_r50(m.band[1] + 100.0), 2300.0), 2900.0)
    cap = ""
    if m.snr < 6.0 and hi > 2300.0:
        hi, cap = 2300.0, " (high edge held at 2300 Hz: under 6 dB SNR the top is hiss)"
    elif m.snr < 10.0 and hi > 2500.0:
        hi, cap = 2500.0, " (high edge held at 2500 Hz: under 10 dB SNR the top is hiss)"
    s["filterLo"], s["filterHi"] = lo, hi
    why.append(("filter", f"{lo:.0f}-{hi:.0f} Hz: the speech heard spans {m.band[0]:.0f}-{m.band[1]:.0f} Hz{cap}"))
    nb = m.impulses >= IMPULSE_RATE
    s["nb"] = nb
    why.append(("nb", f"{'on' if nb else 'off'}: {m.impulses:.1f} impulses a second "
                      f"({'at least' if nb else 'under'} {IMPULSE_RATE:g})"))
    if nb:
        agc, r = "fast", "impulses: a crash must not hold the gain down for a second"
    elif m.snr < NR_OFF_SNR:
        agc, r = "slow", "a weak signal: holding the gain through the pauses keeps the noise between words down"
    else:
        agc, r = "medium", "a strong, steady signal"
    s["agc"] = agc
    why.append(("agc", f"{agc}: {r}"))
    if s["nrStrength"] is None:
        del s["nrStrength"]
    return Choice(True, settings=s, reasons=why, measured=m)


def best_audio(iq: np.ndarray, sideband: str, impulses: float, rate: float = RATE) -> Choice:
    if sideband not in ("usb", "lsb"):
        return Choice(False, why=_("best audio is for USB or LSB voice, not {mode}").format(mode=sideband.upper()))
    m = measure(iq, sideband, impulses, rate)
    if m is None:
        return Choice(False, why=_("nothing in the passband stands above the noise - tune to a station first"))
    # A voice's energy starts within a few hundred hertz of its carrier.
    # When what was heard starts above 800 Hz, the station paused and a
    # neighbour's edge was measured instead (on air, 07/10/2026: "speech
    # 2083-2947 Hz, -3 dB SNR", and a 2300 Hz filter that would have cut
    # the station off when it spoke again).
    if m.band[0] > 800.0 or m.snr < 0.0:
        return Choice(False, why=_("no speech of the station on the dial was heard (what was heard spans "
                                   "{lo:.0f}-{hi:.0f} Hz at {snr:.0f} dB) - try again while they talk").format(
                                     lo=m.band[0], hi=m.band[1], snr=m.snr), measured=m)
    # Its rules are for speech: a beacon or data signal on the dial (the
    # middle beacon was measured as "speech 209-1302 Hz" on air) is said
    # to be one, not given a voice's settings.
    x = np.conj(iq) if sideband == "lsb" else iq
    swing = level_swing(x, m.band[0], m.band[1], rate)
    if swing is not None and swing < MIN_SWING_DB:
        return Choice(False, why=_("the signal on the dial holds its level (within {swing:.1f} dB) - a beacon or "
                                   "a data mode, not speech").format(swing=swing), measured=m)
    return choose(m)


def count_impulses(x: np.ndarray, threshold: float) -> int:
    """How many separate impulses ohscore's NoiseBlanker would blank in this
    block of wideband IQ: runs of samples above threshold x its mean level
    (the same median-based level it uses), counted once per run."""
    mag = np.abs(x)
    m = float(np.median(mag)) * 1.25 + 1e-12
    hit = mag > threshold * m
    if not hit.any():
        return 0
    return int(np.count_nonzero(hit[1:] & ~hit[:-1]) + int(hit[0]))
