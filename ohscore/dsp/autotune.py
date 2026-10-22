"""SSB auto-tune: find where a voice station's suppressed carrier is.

SSB sends no carrier, so there is nothing to lock to; what there is, is
the voice. Two stages, both on a few seconds of the receive channel (12 kHz
complex IQ centred on the dial):

1. **Coarse, from the spectrum.** The averaged spectrum shows the
   station's occupied band. Its carrier side - the lower edge for USB, the
   upper for LSB - sits a transmitter's low cut, usually about 300 Hz,
   from the carrier. That puts the carrier within a hundred hertz or two
   (the low cut is the transmitter's choice, 100-300 Hz), wherever on the
   signal the operator clicked.

2. **Fine, from the pitch harmonics.** Voiced speech is a comb: harmonics
   at k * F0. Mistuned by D, every harmonic lands at k * F0 + D. Each
   voiced frame's magnitude spectrum ripples with period F0, and the phase
   of that ripple says where the comb's teeth are - D modulo F0, measured
   by correlating the spectrum with a comb at every candidate F0 (a
   cepstrum evaluated at any quefrency rather than at FFT bins, with two
   rahmonics added so the comb's teeth are sharp). One frame cannot tell D
   from D + F0 (the comb shifted one tooth looks the same), but pitch
   moves from syllable to syllable while D does not: summing every voiced
   frame's vote over D, the frames agree only at the true offset and their
   aliases smear out. That sum is the measurement.

   The cepstrum's own peak, tried first, measured to a bin of quefrency -
   at 12 kHz a 0.08 ms step, 1-2 Hz of F0 at 120 Hz and so 10-20 Hz of D
   at the top of the band; evaluating the comb at a finely spaced F0 grid
   costs one small matrix product and removes that limit. Which spectrum
   (magnitude, not log or power), which frame (85 ms, not 43) and the
   sharp comb were each chosen on the simulator's voices at 6, 10 and 20
   dB; the per-bin weighting (_comb_frames) on real speech received from
   QO-100 on 07/10/2026, where without it nothing was judged voiced.

It refuses rather than guesses, with a sentence saying why, when:

- nothing near the dial stands above the noise (silence, a dead band);
- what is there is narrower than voice (a carrier, CW, PSK, FT8), wider
  than SSB, or most of its power is in a few steady tones (RTTY);
- too few frames are voiced (a station between overs, breath noise);
- the comb's spacing holds steady (a multi-tone data mode, a heterodyne):
  voice pitch wanders, machines do not, and without that wander the
  alias cannot be ruled out;
- the frames hardly agree, the best fit would put the carrier nearer the
  voice band than most voices' carriers are (MIN_EDGE_GAP) without the
  comb being sure of it or a leaked carrier confirming it, another offset
  fits almost as well, or the first and second halves of the capture,
  measured separately, disagree.
  The last is what keeps it honest on real speech, whose frames agree
  far less well than the simulator's: what was right there was right in
  both halves, and the halves disagreed whenever one of them held only a
  breath or a fragment.

A station whose suppressed carrier leaks shows it as a steady line just
outside its voice. That line is the carrier itself, so when the voice's
harmonics land within 25 Hz of it the line replaces their estimate, and
that agreement is what lets a longer listen answer (Listener); when they
fit there almost as well as where they landed, it refuses (_assist). It
never settles what the harmonics could not: on air a steady line near a
voice is too often something else.

A refusal for want of certainty still says where the voice fitted best
and what fitted nearly as well (`guesses`, best first), and an answer
what fitted next best (`alt`): which of two offsets a pitch apart is right
is what an ear hears at once, so the engine offers them to the operator
(Engine._offer_guesses) rather than either guessing or leaving nothing to
do but listen again.

On the simulator (the table is in the commit message that added this) every
answer it gave at 3-20 dB SNR, both sidebands, was within 4 Hz, and it
refused 4-15 % of 4 s captures. On real QO-100 voice received with a
weak dish it answered about one capture in five, each time within 4-7 Hz
of the station's own leaked carrier. Over the four recordings of
07/10/2026 (the commit that added MIN_EDGE_GAP has the table) it answers
about half the captures of stations whose leaked carrier shows where they
are, 95 % of those answers within 10 Hz. On Brian's recordings of
17/10/2026, with many voices starting under 150 Hz over their carrier,
the commit that made MIN_EDGE_GAP a matter of degree has the before and
after (tools/autotune_replay.py sweep).

Everything is block-vectorised numpy and runs once per request, on a
worker thread, never on the receive thread.

Offsets are carrier minus dial, in the IQ's own terms (a positive offset
means the station's carrier is above the dial), so the corrected dial is
dial + offset whichever the sideband.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

RATE = 12_000.0
# A transmitter's low cut: the audio below it is filtered off, so the
# occupied band starts this far from the carrier. 300 Hz is the common
# default (and the simulator's); real ones range 100-300 Hz, which the
# fine stage's search covers.
LOW_CUT = 300.0
# Voice is wider than every narrow data mode and narrower than anything
# that is not SSB. The top allows for splatter: the simulator's voices,
# through their transmitter's limiter, show 4.1 kHz at 20 dB SNR.
MIN_WIDTH = 600.0
MAX_WIDTH = 4800.0
# Share of an occupied band's power in its three strongest 50 Hz-wide
# lines above which it is tones, not a voice (see coarse()).
MAX_TONAL = 0.7
# How far over the noise floor an occupied run's strongest bin must stand
# to be a signal at all (see coarse()).
MIN_PEAK_DB = 5.0
# Least swing in level (dB, see coarse()) for speech; data holds steady.
MIN_SWING_DB = 4.0
# Furthest from the dial a carrier may be found: a station the operator
# pointed at, not the next one along.
MAX_REACH = 2500.0
# The harmonic search's range around the coarse carrier, in audio terms
# (how far the voice band starts above where LOW_CUT put it). Lopsided on
# purpose: the coarse stage assumed the largest usual low cut, so the real
# carrier can only be nearer the occupied band than it said (up to 200 Hz,
# for a transmitter cutting at 100 Hz), and further away only by the edge
# measurement's own error - which on a weak signal is up to about 100 Hz,
# since the voice band's weak bottom (or top, LSB) is lost in the noise
# and the edge shows inside the band. A narrower search also leaves fewer
# offsets one pitch away to be confused with the right one.
FINE_SPAN = (-150.0, 250.0)
# How much of the receive channel a request listens to. Long enough for
# several syllables at different pitches (what tells the true offset from
# one a pitch away); short enough to wait for.
CAPTURE_SECONDS = 4.0
# Listening until sure (Listener): the first look comes after
# CAPTURE_SECONDS, the next ones every LISTEN_STEP, and it refuses only
# once LISTEN_SECONDS have been heard without the tests passing.
LISTEN_STEP = 1.0
LISTEN_SECONDS = 12.0
# Past the first look, what was heard in each PART_SECONDS (from the
# start) is measured on its own as well, and every part with at least
# MIN_VOICED voiced frames must land within HALVES_HZ of the answer. See
# Listener for why.
PART_SECONDS = 4.0
# The leaked-carrier assist (leaked_carrier, _assist). A transmitter whose
# carrier is not quite suppressed shows it as a steady line just outside
# its voice, exactly where auto-tune is trying to put the dial. On the
# 07/10/2026 recordings these lines are weak - 6-12 dB over the noise in
# a 1 s spectrum, and the strongest line in the carrier's search range
# is as often some other station's or a spur, 100-300 Hz off - so a line
# is never taken alone: see _assist. Each number below was chosen on the
# c1 windows (see the commit that added them).
LINE_BLOCK = 1.0         # s: spectra this long, averaged - a drifting carrier stays in 1-2 bins
LINE_NFFT = 16384        # 0.73 Hz bins at 12 kHz
LINE_DB = 8.0            # over the neighbourhood's median, averaged over what was heard
LINE_UNIQUE_DB = 3.0     # over any other line in the range more than 10 Hz away
LINE_PART_DB = 4.0       # in every PART_SECONDS heard: it was there all along, not a burst
LINE_HZ = 1.5            # how far the line may wander between parts
# Least distance from the voice's occupied band. A transmitter's filter
# passes from 100-300 Hz above its carrier, so a line with voice starting
# nearer than this over it (under it, LSB) is the bottom of the voice or
# something else, not its carrier (Brian, 08/10/2026: 60 Hz). 50 Hz,
# chosen first, made no difference on c1 against 60.
LINE_GAP = 60.0
# The harmonic vote within LINE_COMB_HZ of the line, as a share of the
# best anywhere: the voice's comb must fit there about as well as the
# best fit does (MAX_RIVAL is the same bar for two offsets).
LINE_COMB_HZ = 5.0
LINE_SUPPORT = 0.85
# Frames for the harmonic analysis: 85 ms, a quarter overlapped (hop
# 21 ms), interpolated to 2.9 Hz bins. 43 ms frames were tried first, to
# keep a gliding pitch from smearing the upper harmonics; the longer frame
# resolves a low voice's harmonics properly and was right more often at
# every SNR on the simulator, glides and all.
FRAME = 1024
HOP = 256
NFFT = 4096
F0_LO, F0_HI = 70.0, 400.0
# A frame is voiced when its best comb fit (0..1, 1 a perfect comb)
# reaches this. With the per-bin weighting, noise alone fits at 0.27 in
# the median and 0.37 at most (the best of 640 F0s each frame); speech
# reaches 0.35-0.6 in its voiced syllables. The gate is set low, at the
# noise's median: it only spares the vote frames that are certainly noise,
# and NOISE_FIT and the checks below make the decision.
VOICED = 0.28
MIN_VOICED = 15          # about a third of a second of voiced speech
# Each voiced frame's vote counts by how far its fit stands above this: a
# frame barely over the gate - as likely noise as not - barely counts.
NOISE_FIT = 0.22
# The vote at the best offset, weighted, as a share of the most it could
# be (every voiced frame agreeing exactly). Right answers on the simulator
# score 0.4-0.99 and on real speech 0.2-0.45; this floor only refuses
# what is plainly noise - the next three checks do the real work.
MIN_AGREE = 0.15
# How far ahead of the best offset more than 25 Hz away the best must be.
MAX_RIVAL = 0.85
# The least the carrier may be under the voice's carrier-side edge (over
# it, LSB) as _edge() measures it - the rule pick() uses to choose between
# offsets a pitch apart. On the 07/10/2026 recordings, the stations whose
# own carrier leaked (53 windows, 7 stations) put it 158-412 Hz from the
# edge: a transmitter's low cut plus however far inside the weak bottom of
# the voice the edge is found (one cutting at 100 Hz measured 180-240).
# Every answer that put the carrier nearer than 150 Hz and could be
# checked against a leaked carrier (10 of them) was a pitch too high; the
# nearest right one was 156 Hz. On the simulator (low cut 300 Hz) the gap
# is 230-550 Hz. The far bound is the search's own (FINE_SPAN: 450 Hz),
# which every real station stayed within.
#
# That held on 07/10; on 17/10/2026 it did not. Of the stations measured
# from long stretches of their own speech (tools/autotune_replay.py
# label), about half started their voice 60-120 Hz over their carrier, two
# of them confirmed by the carrier leaking there - an IC-9700 on its
# widest filter passes from 100 Hz - and MIN_EDGE_GAP refused them, or
# chose an offset a pitch under the station. The 07/10 labels could not
# show such stations: they were cut to voices 100 Hz or more over their
# line. So MIN_EDGE_GAP now marks where a carrier becomes unusual, not
# impossible (see pick()):
MIN_EDGE_GAP = 150.0
# ...and this is where it is impossible: a transmitter passes nothing at
# its own carrier, and the edge is measured to within a few tens of hertz.
MIN_FOOT_GAP = 40.0
# Share of the 100 Hz past a voice's edge that must stand over the edge's
# threshold (_edge).
EDGE_UP = 0.7
# The best fit between MIN_FOOT_GAP and MIN_EDGE_GAP from the edge is
# answered all the same when no other possible offset fits within this
# share of it and both halves of what was heard agree (judge()). Chosen on
# 17/10 and c3 (07/10) together: at 0.7 the near answers were 12 right and
# none wrong on 17/10, 11 right and 3 wrong (and 7 on another voice) on c3;
# at 0.75-0.85 the wrong ones grew faster than the right.
NEAR_RIVAL = 0.7
# Switches for what 17/10/2026 changed, kept so tools/autotune_replay.py
# --set can score the old behaviour against the new on any recording:
# - NEAR_DECIDES: the edge picks the offset a pitch under a near best fit
#   when that fits within MAX_RIVAL of it. Off: on 17/10 it took 12 wrong
#   answers of 172 and no right ones; on c3, 8 wrong and 1 right.
# - NEAR_LINE: a leaked carrier where the near best fit puts it confirms it.
# - RIVAL_POSSIBLE: an answer's rival is any possible offset, near ones
#   included (on c3: 5 fewer wrong answers, 2 fewer right).
NEAR_DECIDES = False
NEAR_LINE = True
RIVAL_POSSIBLE = True
# The first and second halves of the capture, each measured on its own,
# must land within this of each other.
HALVES_HZ = 10.0
# Voice pitch wanders by several per cent between syllables; a comb whose
# spacing holds steadier than this is a machine (a multi-tone data mode's
# carriers measure 0.1 %; conversation, 6-40 %).
MIN_PITCH_SPREAD = 0.02


@dataclass
class Tune:
    """What auto-tune found. `ok` False means refused: `why` says why."""
    ok: bool
    offset: float = 0.0          # carrier - dial, Hz (dial + offset is the carrier)
    why: str = ""
    sideband: str = "usb"
    coarse: float | None = None  # the carrier from the spectrum alone
    band: tuple[float, float] | None = None   # occupied band, Hz from the dial
    voiced: int = 0
    frames: int = 0
    agree: float = 0.0           # 0..1, see MIN_AGREE
    rival: float = 0.0           # best other offset's score / the best
    pitch: float = 0.0           # median F0 of the voiced frames, Hz
    details: dict = field(default_factory=dict)


# ----------------------------------------------------------------- spectrum
def psd(iq: np.ndarray, rate: float = RATE, nper: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    """Welch's averaged periodogram (Hann, half overlap), fft-shifted:
    frequencies (Hz from the dial) and power per bin."""
    iq = np.asarray(iq, np.complex64)
    if len(iq) < nper:
        nper = max(16, len(iq))
    step = nper // 2
    frames = np.lib.stride_tricks.sliding_window_view(iq, nper)[::step]
    w = np.hanning(nper).astype(np.float32)
    P = np.mean(np.abs(np.fft.fft(frames * w, axis=1)) ** 2, axis=0) / np.sum(w ** 2)
    f = np.fft.fftfreq(nper, 1 / rate)
    return np.fft.fftshift(f), np.fft.fftshift(P)


def _smooth(x: np.ndarray, n: int, axis: int = -1) -> np.ndarray:
    """Centred moving average of n points (edges averaged over what exists)."""
    if n <= 1:
        return x
    x = np.moveaxis(x, axis, -1)
    pad = n // 2
    c = np.cumsum(np.concatenate([np.zeros(x.shape[:-1] + (1,)), x], axis=-1), axis=-1)
    idx = np.arange(x.shape[-1])
    lo = np.clip(idx - pad, 0, x.shape[-1])
    hi = np.clip(idx + pad + 1, 0, x.shape[-1])
    out = (c[..., hi] - c[..., lo]) / (hi - lo)
    return np.moveaxis(out, -1, axis)


def noise_floor(P: np.ndarray, f: np.ndarray, reach: float = 4500.0) -> float:
    """Noise power per bin: a low percentile of the spectrum within the
    channel's flat part. Signals - even several - cover less than most of
    it; the 20th percentile is noise wherever the band is not wall to wall."""
    inside = np.abs(f) <= reach
    return float(np.percentile(P[inside], 20))


def occupied(f: np.ndarray, P: np.ndarray, floor: float, rise_db: float = 2.5,
             bridge_hz: float = 120.0) -> list[tuple[float, float]]:
    """Runs of the (60 Hz smoothed) spectrum standing rise_db above the
    floor, gaps narrower than bridge_hz joined (the space between two
    formants is not the end of a signal). Returns [(lo, hi)] in Hz."""
    df = float(f[1] - f[0])
    s = _smooth(P, max(1, int(round(60.0 / df))))
    on = s > floor * 10 ** (rise_db / 10)
    runs, start = [], None
    for i, v in enumerate(np.append(on, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append([start, i - 1])
            start = None
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and (a - merged[-1][1]) * df <= bridge_hz:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(float(f[a]) - df / 2, float(f[b]) + df / 2) for a, b in merged]


def _edge(f: np.ndarray, P: np.ndarray, floor: float, lo: float, hi: float, upper: bool) -> float:
    """The carrier-side edge of an occupied band, to a few hertz.

    The band's body is its 80th-percentile level; the edge is where the
    lightly smoothed spectrum, looked at from the carrier side inwards,
    first reaches within 10 dB of that body (or halfway up from the floor,
    if the signal stands less than 20 dB out of the noise) and stays up for
    the next 100 Hz. A fixed rise over the floor was tried first: on a
    strong signal it found the transmitter's skirt below the low cut - the
    splatter of its limiter and the syllable envelope - a hundred hertz
    and more before the voice band really starts."""
    df = float(f[1] - f[0])
    s = 10 * np.log10(_smooth(P, max(1, int(round(25.0 / df)))) + 1e-30)
    fl = 10 * np.log10(floor + 1e-30)
    inside = (f >= lo) & (f <= hi)
    body = float(np.percentile(s[inside], 80)) if inside.any() else fl + 6
    thr = max(fl + 0.5 * (body - fl), body - 10.0)
    look = np.nonzero((f >= lo - 150.0) & (f <= hi + 150.0))[0]
    if upper:
        look = look[::-1]
    run = max(1, int(round(100.0 / df)))
    for j, i in enumerate(look):
        nxt = look[j:j + run]
        # Most of the next 100 Hz up, not their average: a station's leaked
        # carrier, 80-90 Hz under a voice that starts low, lifted the
        # average over the gap between them, and the edge was found on the
        # carrier itself - which put the carrier outside the harmonics'
        # search, and every listen to that station on 17/10/2026 refused.
        if s[i] >= thr and np.mean(s[nxt] >= thr) >= EDGE_UP:
            prev = look[j - 1] if j > 0 else i
            a, b = s[prev], s[i]
            # Interpolated between the bins either side of the crossing.
            frac = (thr - a) / (b - a) if b != a and prev != i else 0.0
            return float(f[prev] + (f[i] - f[prev]) * frac)
    return hi if upper else lo


def level_swing(iq: np.ndarray, lo: float, hi: float, rate: float = RATE) -> float | None:
    """How far, in dB, the power in [lo, hi] Hz swings between 43 ms
    frames (90th over 10th percentile): syllables and pauses make it 7 dB
    or more for speech; a data signal holds steady. None if too short."""
    n = len(iq) // 512
    if n < 8:
        return None
    x = np.asarray(iq, np.complex64)[:n * 512].reshape(n, 512)
    S = np.abs(np.fft.fft(x * np.hanning(512), axis=1)) ** 2
    fb = np.fft.fftfreq(512, 1 / rate)
    pw = S[:, (fb >= lo) & (fb <= hi)].sum(axis=1)
    return float(10 * np.log10(np.percentile(pw, 90) / max(np.percentile(pw, 10), 1e-30)))


def coarse(iq: np.ndarray, sideband: str, rate: float = RATE) -> tuple[float | None, tuple | None, str]:
    """(carrier offset from the dial, occupied band, why refused). The
    signal chosen is the one whose reach - carrier to far edge - covers the
    dial, else the one whose carrier is nearest it."""
    f, P = psd(iq, rate)
    floor = noise_floor(P, f)
    segs = []
    for a, b in occupied(f, P, floor):
        if abs(a) >= 5000 or abs(b) >= 5000:
            continue
        inside = (f >= a) & (f <= b)
        peak = float(P[inside].max())
        # A run whose best bin is only a few dB up is the noise's own lumps,
        # not a signal: one stood between the dial and the voice beside it,
        # and the simulator's noise (drawn from a bank of 24 blocks, so not
        # quite white) makes runs 300 Hz wide and 4 dB high on an empty band.
        # A voice even at 3 dB SNR peaks well over this in its formants.
        if peak < floor * 10 ** (MIN_PEAK_DB / 10):
            continue
        segs.append((a, b, inside))
    if not segs:
        return None, None, "nothing near the dial stands above the noise"
    lsb = sideband == "lsb"
    cands = []
    for a, b, inside in segs:
        carrier = (b + LOW_CUT) if lsb else (a - LOW_CUT)
        reach = (a, carrier) if lsb else (carrier, b)
        covers = reach[0] - 100.0 <= 0.0 <= reach[1] + 100.0
        # Narrow runs come last among those that cover the dial: a station
        # whose carrier is not quite suppressed shows a line just below its
        # voice (USB), inside the voice's reach - on air on 07/10/2026 that
        # line, not the voice beside it, was being judged and refused.
        cands.append((not covers, b - a < MIN_WIDTH, abs(carrier), a, b, inside))
    cands.sort(key=lambda c: c[:3])
    *_, a, b, inside = cands[0]
    width = b - a
    p = P[inside]
    if width < MIN_WIDTH:
        return None, (a, b), (f"the signal there is {width:.0f} Hz wide - a carrier, CW or a data mode, "
                              f"not SSB voice")
    if width > MAX_WIDTH:
        return None, (a, b), f"the signal there is {width / 1000:.1f} kHz wide - wider than SSB voice"
    # A voice's averaged spectrum is smooth: its pitch moves, so no
    # harmonic stays put. Most of the power in a few steady lines is tones -
    # RTTY's two, an MFSK or multi-carrier modem's few.
    df = float(f[1] - f[0])
    w = max(1, int(round(25.0 / df)))
    q = p.copy()
    lines = 0.0
    for _ in range(3):
        k = int(np.argmax(q))
        lines += float(q[max(0, k - w):k + w + 1].sum())
        q[max(0, k - w):k + w + 1] = 0.0
    tonal = lines / float(p.sum())
    if tonal > MAX_TONAL:
        return None, (a, b), (f"{tonal * 100:.0f} % of the signal's power is in a few steady tones - a data mode "
                              f"such as RTTY, not a voice")
    # Speech comes in syllables and pauses; a data signal holds its level.
    # The middle beacon (400 Bd BPSK, 1.6 kHz wide) passed every other
    # test on air on 07/10/2026 - its Manchester spectrum is a comb at
    # 200 Hz - and was "landed" in four different places. Over 43 ms
    # frames, the occupied band's 90th to 10th percentile power spans 7 dB
    # and more for voices even at 3 dB SNR (16-24 dB at 20 dB), and under
    # 2 dB for the beacon, RTTY and the simulator's data modes.
    swing = level_swing(iq, a, b, rate)
    if swing is not None and swing < MIN_SWING_DB:
        return None, (a, b), (f"its level holds steady (within {swing:.1f} dB) - a beacon or a data mode, "
                              f"not speech")
    edge = _edge(f, P, floor, a, b, upper=lsb)
    carrier = edge + LOW_CUT if lsb else edge - LOW_CUT
    if abs(carrier) > MAX_REACH:
        # Nothing of a voice's own near the dial; the nearest is some way
        # off, and on 07/10 one 5 kHz away was taken - not what anyone
        # pressing auto-tune on a frequency means.
        return None, (a, b), (f"nothing near the dial stands above the noise (the nearest voice's carrier is "
                              f"{carrier / 1000:+.1f} kHz away)")
    return carrier, (a, b), ""


# --------------------------------------------------------- harmonic comb
_F0 = np.geomspace(F0_LO, F0_HI, 640)     # 0.27 % steps: 0.3 Hz at 120 Hz
# The comb's shape: the ripple's fundamental and its next two rahmonics,
# so the comb has sharp teeth rather than a cosine's broad ones. With a
# cosine alone, a comb at half the pitch fitted almost as well as the
# right one (every other tooth on a harmonic, the rest on nothing), and
# so did an offset one pitch away whenever the pitch moved little; with
# sharp teeth the extra ones land in the valleys between harmonics and
# score against themselves, and a pitch a few per cent off misses.
RAHMONICS = (1.0, 0.7, 0.4)


def _demod(iq: np.ndarray, carrier: float, sideband: str, rate: float, n0: int = 0) -> np.ndarray:
    """The capture with `carrier` moved to 0 Hz and turned upright (LSB
    mirrored), so a voice's harmonics sit at positive audio frequencies.
    `n0` is the first sample's index in the whole listen, so pieces
    demodulated separately join in phase."""
    t = (n0 + np.arange(len(iq))) / rate
    a = np.asarray(iq, np.complex128) * np.exp(-2j * np.pi * carrier * t)
    return np.conj(a) if sideband == "lsb" else a


def _bins(top: float, rate: float) -> tuple[np.ndarray, np.ndarray]:
    """The FFT bins the comb looks at (audio 200 Hz .. top): mask, frequencies."""
    fa = np.fft.fftfreq(NFFT, 1 / rate)
    band = (fa >= 200.0) & (fa <= top)
    return band, fa[band]


def _ripple(a: np.ndarray, band: np.ndarray, fb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per 85 ms frame of the demodulated audio `a`: the magnitude
    spectrum's ripple (the spectrum less its envelope) and the envelope."""
    frames = np.lib.stride_tricks.sliding_window_view(a, FRAME)[::HOP]
    S = np.fft.fft(frames * np.hanning(FRAME), NFFT, axis=1)
    # Magnitude, not power and not log: power lets the one strongest
    # formant decide, and a log spectrum gives the noise between and above
    # the harmonics as much say as the harmonics - at 6 dB it put half the
    # answers a pitch away. Magnitude was best on the simulator's voices
    # at every SNR tried.
    A = np.abs(S[:, band])
    # Take out the envelope (formants, the transmitter's response): a
    # 300 Hz moving average holds two to four harmonics of any voice, so
    # it keeps the shape and drops the ripple.
    env = _smooth(A, int(round(300.0 / (fb[1] - fb[0]))) | 1, axis=1)
    return A - env, env


def _combs(fb: np.ndarray) -> list[np.ndarray]:
    """The comb at every F0 in _F0, one matrix per rahmonic (bins x F0)."""
    return [np.exp(-2j * np.pi * m * np.outer(fb, 1.0 / _F0)) for m in range(1, len(RAHMONICS) + 1)]


def _comb_frames(X: np.ndarray, env: np.ndarray, noise: np.ndarray, combs: list[np.ndarray]):
    """Per frame: the comb correlation of the ripple X at every F0 in _F0,
    for each rahmonic: rahmonic x frame x F0, normalised so that a perfect
    cosine ripple of any amplitude scores 1.

    Each bin counts by how far the voice's envelope stands over the noise
    there (a Wiener gain on the envelope, `noise` being each bin's
    quiet-quartile envelope across what has been heard). Real speech on air
    (07/10/2026) has its harmonics in a kilohertz or so of formant and
    little above the noise elsewhere; unweighted, those noise-only bins
    held most of each frame's ripple energy and real voiced frames scored
    like noise."""
    v = np.clip(1.0 - (noise / np.maximum(env, 1e-30)) ** 2, 0.0, 1.0)
    Xw = X * v
    # A perfect cosine ripple over the weighted bins scores 1.
    norm = np.sqrt(np.sum(v * X ** 2, axis=1) * np.sum(v, axis=1) / 2.0) + 1e-30
    return np.stack([(Xw @ E) / norm[:, None] for E in combs])


def _pitches(C: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Each frame's pitch: (harmonicity 0..1, the index into _F0 of the F0
    whose sharp comb fits its spectrum best, the rahmonics' correlations
    there - rahmonic x frame). All the vote needs of a frame; the rest of
    C is dropped, so a long listen keeps a few numbers per frame."""
    w = np.asarray(RAHMONICS)
    Hs = np.tensordot(w, np.abs(C), axes=1) / w.sum()
    k = np.argmax(Hs, axis=1)
    idx = np.arange(len(k))
    return Hs[idx, k], k, C[:, idx, k]


def _best(d: np.ndarray, total: np.ndarray, allowed: np.ndarray) -> tuple[int, float, float]:
    """(index, interpolated offset, the best other score more than 25 Hz
    away) over the offsets `allowed` of the landscape `total`."""
    t = np.where(allowed, total, -np.inf)
    i = int(np.argmax(t))
    # Parabolic interpolation between grid points.
    frac = 0.0
    if 0 < i < len(d) - 1 and allowed[i - 1] and allowed[i + 1]:
        y0, y1, y2 = total[i - 1], total[i], total[i + 1]
        den = y0 - 2 * y1 + y2
        if den < 0:
            frac = 0.5 * (y0 - y2) / den
    far = allowed & (np.abs(d - d[i]) > 25.0)
    return i, float(d[i] + frac * (d[1] - d[0])), float(t[far].max()) if far.any() else -np.inf


def pick(d: np.ndarray, total: np.ndarray, edge: float = LOW_CUT, dial: tuple[float, float] = (0.0, 1.0)):
    """The offset (audio Hz from the coarse carrier) the summed vote
    `total` over the offsets `d` points to: (index, offset, best rival's
    score, the offsets considered, why it cannot say or "", a sentence when
    the edge decided between offsets or ""). `edge` is where the voice's
    carrier-side edge is in the same audio terms: LOW_CUT over the coarse
    carrier, which is where coarse() put it. `dial` (base, sign) turns an
    offset into Hz from the dial for the sentences (base + sign * offset):
    what an operator can compare with the guesses offered beside them.

    Offsets that fit almost as well as the best are a pitch apart, or two -
    the comb one tooth over, or at half or double the pitch. The spectrum's
    edge tells some of them apart, in two ways.

    - Nothing is heard under a USB carrier (over it, LSB): an offset that
      puts the carrier less than MIN_FOOT_GAP under the voice's edge is not
      its carrier, and is never considered at all.
    - A carrier between MIN_FOOT_GAP and MIN_EDGE_GAP under the edge is
      possible but unusual, and a pitch too high is the commoner reason
      for a fit there. Only the offsets at least MIN_EDGE_GAP under it are
      `allowed`; one of them is taken if it fitted nearly as well as the
      best of all (MAX_RIVAL, and NEAR_DECIDES) and stands clear of the
      rest it allows. If the best possible fit is nearer and clearly
      ahead, nothing is decided: it is refused (judge() then offers it as
      a guess, and a leaked carrier may still confirm it - _assist)."""
    def w(x):
        return dial[0] + dial[1] * x

    possible = d <= edge - MIN_FOOT_GAP
    if not possible.any():
        possible = np.ones(len(d), bool)
    a, delta_a, _ = _best(d, total, np.ones(len(d), bool))
    i, delta, _ = _best(d, total, possible)
    allowed = d <= edge - MIN_EDGE_GAP
    j, dj, rj = _best(d, total, allowed)
    if total[a] > 0 and total[i] < MAX_RIVAL * total[a]:
        # What fits best of all cannot be the carrier, and nothing that can
        # fits nearly as well: nothing the voice hardly voted for is
        # promoted.
        return j, dj, rj, allowed, (f"the best fit ({w(delta_a):+.0f} Hz) puts the carrier {edge - delta_a:.0f} Hz "
                                    f"from the voice's edge, nearer than a voice's own"), ""
    if not (total[i] > 0 and total[j] >= MAX_RIVAL * total[i] and NEAR_DECIDES) and abs(d[j] - d[i]) > 0.75:
        return j, dj, rj, allowed, (f"the best fit ({w(delta):+.0f} Hz) puts the carrier {edge - delta:.0f} Hz from "
                                    f"the voice's edge, nearer than a voice's own"), ""
    # The answer's rival is the best other offset that is possible at all,
    # not only among those allowed: one nearer the edge than MIN_EDGE_GAP
    # is too unusual to be taken on the comb's word, but not so unusual
    # that the comb's choice beside it is sure. On 17/10/2026 a station
    # whose voice started 70 Hz over its leaked carrier was landed a pitch
    # under it at the first look, four times in five, its true carrier
    # fitting almost as well as the answer and never counted as a rival.
    far = possible & (np.abs(d - d[j]) > 25.0)
    if RIVAL_POSSIBLE and far.any():
        rj = max(rj, float(total[far].max()))
    decided = ""
    if abs(d[j] - d[i]) > 25.0:
        decided = (f"{w(delta):+.0f} Hz would put the carrier {edge - delta:.0f} Hz from the voice's edge, too "
                   f"near; {w(dj):+.0f} Hz puts it {edge - dj:.0f} Hz")
    return j, dj, rj, allowed, "", decided


def judge(h: np.ndarray, k: np.ndarray, c: np.ndarray, edge: float = LOW_CUT,
          span: tuple[float, float] = FINE_SPAN, part: int = 0, dial: tuple[float, float] = (0.0, 1.0)) -> dict:
    """The harmonic stage's verdict on the frames heard so far (as
    _pitches gives them: harmonicity, F0 index, rahmonic correlations),
    the voice's edge being `edge` audio Hz above the carrier they were
    demodulated with. Returns a dict: `delta` (Hz, in audio terms:
    harmonics sit at k F0 + delta), `voiced`, `frames`, `agree`, `rival`,
    `pitch`, `spread`, `landscape` (the offsets searched and the vote at
    each), `parts`, and `why` when it cannot say. With `part` (frames),
    the frames are also judged in consecutive parts that long, each by
    itself (Listener: a voice heard at different times must be heard in
    the same place)."""
    out = {"delta": 0.0, "voiced": 0, "frames": 0, "agree": 0.0, "rival": 1.0, "pitch": 0.0, "spread": 0.0,
           "why": ""}
    out["frames"] = len(h)
    voiced = h >= VOICED
    out["voiced"] = int(voiced.sum())
    if out["voiced"] < MIN_VOICED:
        out["why"] = (f"no voice heard: {out['voiced']} of {len(h)} frames had pitch harmonics "
                      f"(needs {MIN_VOICED})")
        return out
    w = np.asarray(RAHMONICS)
    f0 = _F0[k[voiced]]
    c = c[:, voiced]                                   # rahmonic x voiced frame
    # The search is placed against the edge: FINE_SPAN around where
    # LOW_CUT under the edge would put the carrier.
    d = edge - LOW_CUT + np.arange(span[0], span[1] + 0.25, 0.5)
    # Ripple phase: X ~ cos(2 pi (f - delta) / F0), so rahmonic m's
    # correlation ~ exp(-2j pi m delta / F0), and Re(C_m e^{2j pi m d / F0})
    # peaks at d = delta; the weighted sum is the frame's vote for each
    # offset, its harmonicity at most. Weighting by harmonicity again lets
    # the clearest frames speak loudest.
    ph = np.exp(2j * np.pi * np.outer(1.0 / f0, d))
    vote = sum(a * np.real(c[m][:, None] * ph ** (m + 1)) for m, a in enumerate(RAHMONICS)) / w.sum()
    hv = h[voiced]
    wt = np.maximum(hv - NOISE_FIT, 0.0)

    def landscape(sel):
        return (vote[sel] * wt[sel, None]).sum(axis=0) / max(float(np.sum(wt[sel] * hv[sel])), 1e-30)

    every = np.ones(len(hv), bool)
    total = landscape(every)
    out["landscape"] = (d, total)

    i, delta, rival_v, allowed, edge_why, decided = pick(d, total, edge, dial)

    def w(x):
        return dial[0] + dial[1] * x
    if decided:
        out["tiebreak"] = decided
    # The same measurement from the first and the second half of what was
    # heard, separately: two independent answers that must agree - among
    # the offsets the edge allows, when it broke a tie.
    half = np.arange(len(hv)) < len(hv) // 2
    halves = [float(d[int(np.argmax(np.where(allowed, landscape(s), -np.inf)))]) for s in (half, ~half)]
    parts = []
    if part:
        when = np.flatnonzero(voiced) // part
        for q in range(int(when.max()) + 1):
            sel = when == q
            if sel.sum() >= MIN_VOICED:
                parts.append(float(d[int(np.argmax(np.where(allowed, landscape(sel), -np.inf)))]))
    out["parts"] = parts
    out["agree"] = float(total[i])
    out["rival"] = float(max(0.0, rival_v) / total[i]) if total[i] > 0 else 1.0
    out["halves"] = halves
    out["delta"] = delta
    out["pitch"] = float(np.median(f0))
    out["spread"] = float(np.std(np.log(f0)))
    if out["spread"] < MIN_PITCH_SPREAD:
        out["why"] = (f"the tones are evenly spaced at a steady {out['pitch']:.0f} Hz - a data mode or a "
                      f"heterodyne, not a voice")
    elif out["agree"] < MIN_AGREE:
        out["why"] = (f"the voiced frames do not agree on an offset (agreement {out['agree']:.2f}, "
                      f"needs {MIN_AGREE})")
    elif edge_why:
        out["why"] = edge_why
        possible = d <= edge - MIN_FOOT_GAP
        n = int(np.argmax(np.where(possible, total, -np.inf)))
        if d[n] > edge - MIN_EDGE_GAP and total[n] >= MAX_RIVAL * total.max():
            # Refused only for putting the carrier nearer the voice's edge
            # than most transmitters do (MIN_EDGE_GAP), not as near as none
            # can (MIN_FOOT_GAP) - where about half the stations measured on
            # 17/10/2026 put theirs, and auto-tune refused or landed a pitch
            # off nearly every listen to them (see MIN_EDGE_GAP). So the
            # near fit is answered all the same when the comb leaves no
            # doubt - no other possible offset fits nearly as well
            # (NEAR_RIVAL) and both halves (and every part) of what was
            # heard put it there - or when a leaked carrier confirms it
            # (_assist, `near`). Otherwise it stays refused, and is offered
            # first among the guesses.
            out["near"] = float(d[n])
            far = possible & (np.abs(d - d[n]) > 25.0)
            out["near_rival"] = (float(max(0.0, total[far].max()) / total[n]) if far.any() and total[n] > 0
                                 else 1.0)
            hp = [float(d[int(np.argmax(np.where(possible, landscape(q), -np.inf)))]) for q in (half, ~half)]
            pp = []
            if part:
                for q in range(int(when.max()) + 1):
                    sel = when == q
                    if sel.sum() >= MIN_VOICED:
                        pp.append(float(d[int(np.argmax(np.where(possible, landscape(sel), -np.inf)))]))
            if (out["near_rival"] < NEAR_RIVAL and max(abs(x - d[n]) for x in hp) <= HALVES_HZ
                    and not (pp and max(abs(x - d[n]) for x in pp) > HALVES_HZ)):
                out["delta"], out["rival"], out["why"] = out["near"], out["near_rival"], ""
                out["agree"] = float(total[n])
                out["near_answer"] = True
    elif out["rival"] > MAX_RIVAL:
        out["why"] = (f"two offsets fit almost equally ({w(delta):+.0f} Hz and another {out['rival'] * 100:.0f} % "
                      f"as good), and the edge of the voice's spectrum allows both")
    elif part and decided:
        # Past the first look, the edge rule may refuse an offset but not
        # choose one: an answer the comb could not tell from one a pitch
        # away, picked because the other was too near the edge, was right
        # at 4 s about as often as the edge is, and listening on gave it
        # more chances: on the c3 labels this took 19 wrong answers of the
        # listener's and no right ones, and changed nothing on c1.
        out["why"] = (f"two offsets a pitch apart fit almost equally, and only the edge of the voice's "
                      f"spectrum chose between them ({decided})")
    elif parts and max(abs(p - d[i]) for p in parts) > HALVES_HZ:
        out["why"] = ("what was heard at different times disagrees (" + ", ".join(f"{w(p):+.0f}" for p in parts)
                      + " Hz): two stations taking turns, or one never clear")
    elif abs(halves[0] - halves[1]) > HALVES_HZ:
        out["why"] = (f"the first and second halves of what was heard disagree ({w(halves[0]):+.0f} and "
                      f"{w(halves[1]):+.0f} Hz)")
    # A refusal for want of certainty, not for want of a voice, still
    # knows where the voice fits best and what fits nearly as well: the
    # operator can tell the two apart by ear at once (one sounds right,
    # the other a pitch off), so both are kept to be offered (`guesses`,
    # best first; Engine.auto_tune applies them on a second press).
    if not out["why"]:
        # The answer's own next best, a pitch or so away: offered after the
        # answer is applied, in case the ear says it is the wrong one.
        possible = d <= edge - MIN_FOOT_GAP
        far = possible & (np.abs(d - out["delta"]) > 25.0)
        if far.any() and total[far].max() > 0:
            out["alt"] = float(d[far][int(np.argmax(total[far]))])
    if out["why"] and out["spread"] >= MIN_PITCH_SPREAD and out["agree"] >= MIN_AGREE:
        possible = d <= edge - MIN_FOOT_GAP
        if not possible.any():
            possible = np.ones(len(d), bool)
        top = float(d[possible][int(np.argmax(total[possible]))])
        far = possible & (np.abs(d - top) > 25.0)
        alt = float(d[far][int(np.argmax(total[far]))]) if far.any() and total[far].max() > 0 else None
        out["guesses"] = [top] + ([alt] if alt is not None else [])
    return out


def fine(iq: np.ndarray, carrier: float, sideband: str, top: float = 2800.0, rate: float = RATE,
         span: tuple[float, float] = FINE_SPAN) -> dict:
    """The harmonic stage around a coarse carrier, on one capture: see judge()."""
    if len(iq) < FRAME:
        return {"delta": 0.0, "voiced": 0, "frames": 0, "agree": 0.0, "rival": 1.0, "pitch": 0.0, "spread": 0.0,
                "why": "too little audio to measure"}
    band, fb = _bins(top, rate)
    X, env = _ripple(_demod(iq, carrier, sideband, rate), band, fb)
    C = _comb_frames(X, env, np.percentile(env, 25, axis=0), _combs(fb))
    return judge(*_pitches(C), span=span, dial=(carrier, 1.0 if sideband == "usb" else -1.0))


# ---------------------------------------------------------- leaked carrier
def leaked_carrier(iq: np.ndarray, lo: float, hi: float, rate: float = RATE) -> tuple[float, float] | None:
    """A steady line between lo and hi Hz (from the dial) that could be a
    station's leaked carrier: (frequency, dB over its neighbourhood), or
    None. It must be the strongest in the range by LINE_UNIQUE_DB, stand
    LINE_DB out on everything heard and LINE_PART_DB out in every
    PART_SECONDS of it, at the same place. Needs 4 s at least.

    Spectra of LINE_BLOCK, averaged, rather than one long FFT: one long
    FFT gains on a steady line but loses it when the downlink drifts a
    few hertz over 12 s, which on 07/10/2026 it did."""
    n = int(LINE_BLOCK * rate)
    blocks = len(iq) // n
    per_part = int(round(PART_SECONDS / LINE_BLOCK))
    if blocks < per_part:
        return None
    x = np.asarray(iq[:blocks * n], np.complex64).reshape(blocks, n) * np.hanning(n).astype(np.float32)
    S = np.abs(np.fft.fft(x, LINE_NFFT, axis=1)) ** 2
    f = np.fft.fftfreq(LINE_NFFT, 1 / rate)
    span = (f >= lo) & (f <= hi)
    if not span.any():
        return None
    avg = S.mean(axis=0)
    i = int(np.flatnonzero(span)[np.argmax(avg[span])])
    hood = (f >= lo - 150.0) & (f <= hi + 150.0) & (np.abs(f - f[i]) > 5.0)
    ref = max(float(np.median(avg[hood])), 1e-30)
    db = 10 * np.log10(avg[i] / ref)
    if db < LINE_DB:
        return None
    other = span & (np.abs(f - f[i]) > 10.0)
    if other.any() and db - 10 * np.log10(avg[other].max() / ref) < LINE_UNIQUE_DB:
        return None
    here = np.abs(f - f[i]) <= LINE_HZ
    for q in range(0, blocks - per_part + 1, per_part):
        a = S[q:q + per_part].mean(axis=0)
        if 10 * np.log10(a[here].max() / max(float(np.median(a[hood])), 1e-30)) < LINE_PART_DB:
            return None
    y0, y1, y2 = avg[i - 1], avg[i], avg[(i + 1) % LINE_NFFT]
    den = y0 - 2 * y1 + y2
    frac = 0.5 * (y0 - y2) / den if den < 0 else 0.0
    return float(f[i] + frac * (f[1] - f[0])), float(db)


def _assist(r: dict, iq: np.ndarray, base: float, sign: float, band: tuple[float, float] | None,
            rate: float = RATE, edge: float | None = None) -> dict:
    """judge()'s verdict `r` with the leaked carrier's evidence added.
    `base` is the carrier the frames were demodulated with (Hz from the
    dial) and `sign` +1 for USB, -1 for LSB, so offset d in r's terms is
    base + sign * d from the dial. Pops r's landscape.

    The line is looked for where the comb's search could put the carrier
    and at least LINE_GAP outside the voice's occupied band - a line
    inside the band is not under the voice, whatever else it is (one 36 Hz
    inside it, with the comb fitting there, was the only wrong answer the
    assist gave before this rule). Then, only if what was heard is a voice
    whose frames agree (the pitch wanders, agreement over MIN_AGREE) and
    its comb fits at the line nearly as well as anywhere (LINE_SUPPORT):

    - answered already, within 25 Hz of the line: the line, which is the
      carrier itself rather than an estimate of it (`how` "line": the
      two agree, which is what lets a later look answer - see Listener);
    - answered already, elsewhere: refused - two places fit, and one of
      them is a carrier.

    A refusal stands, whatever the line. Letting the line decide a
    refusal (two offsets a pitch apart, the halves, the edge rule) was
    tried and is not done: on c1 it added 20 right answers and no wrong
    ones, but on the labelled c3 (69 stations) 29 right and 10 wrong -
    a second steady line under a voice, or one belonging to the next
    station, with the comb fitting there as well as it fits anywhere,
    is common enough that a line alone must not settle what the comb
    could not.

    The other way round - refusing a comb answer whenever any qualifying
    line disagrees, whether the comb fits on it or not - was tried for
    the one station c1 still gets wrong (eve16-0157: its line found 3 Hz
    from the truth, the comb's vote there below zero, the comb's answer a
    pitch off). It changed nothing on c1 and would refuse right answers
    whenever a spur sits under a voice, so it was not kept."""
    land = r.pop("landscape", None)
    if land is None:
        return r
    d, total = land
    lo, hi = sorted((base + sign * d[0], base + sign * d[-1]))
    # The voice starts at its edge (Hz from the dial), as _edge measures
    # it; the occupied band's own end is used when that is not known. The
    # band is the worse measure: a leaked carrier within its 120 Hz bridge
    # of the voice is part of it, so the line was looked for only below
    # itself - for a transmitter passing from 80 Hz (17/10/2026), never.
    foot = edge if edge is not None else (None if band is None else (band[0] if sign > 0 else band[1]))
    if foot is not None:
        if sign > 0:
            hi = min(hi, foot - LINE_GAP)
        else:
            lo = max(lo, foot + LINE_GAP)
    if hi <= lo:
        return r
    line = leaked_carrier(iq, lo, hi, rate)
    if line is None:
        return r
    freq, db = line
    dl = sign * (freq - base)
    r["line"] = (freq, db)
    if r["spread"] < MIN_PITCH_SPREAD or r["agree"] < MIN_AGREE or total.max() <= 0:
        return r
    near = np.abs(d - dl) <= LINE_COMB_HZ
    support = float(total[near].max() / total.max()) if near.any() else 0.0
    r["line_support"] = support
    if support < LINE_SUPPORT:
        return r
    if r.get("near") is not None and NEAR_LINE and abs(r["near"] - dl) <= 25.0:
        # Refused only because the best fit put the carrier nearer the
        # voice's edge than most transmitters do - and there is the
        # carrier, where the harmonics put it. Some transmitters really do
        # (an IC-9700's widest transmit filter passes from 100 Hz): two
        # stations in Brian's recording of 17/10/2026 started their voice
        # 70-90 Hz over their own leaked carrier.
        r["delta"], r["how"], r["why"] = dl, "line", ""
        r.pop("guesses", None)
        r.pop("alt", None)
    elif not r["why"]:
        if abs(r["delta"] - dl) <= 25.0:
            r["delta"], r["how"] = dl, "line"
            r.pop("alt", None)
        else:
            r["why"] = (f"the voice's harmonics fit best {sign * (r['delta'] - dl):+.0f} Hz from a steady line "
                        f"where its leaked carrier would be, and almost as well on the line")
    return r


def _top(band: tuple[float, float]) -> float:
    """How high in audio the comb looks: the voice's width over its low cut."""
    return min(3000.0, max(1500.0, band[1] - band[0] + LOW_CUT + 200.0))


def auto_tune(iq: np.ndarray, sideband: str, rate: float = RATE) -> Tune:
    """Both stages on one capture of the receive channel centred on the
    dial, however long it is (CAPTURE_SECONDS is what it was built for).
    Listener is the same measurement listening until it is sure."""
    if sideband not in ("usb", "lsb"):
        return Tune(False, why=f"auto-tune works on USB or LSB voice, not {sideband.upper()}", sideband=sideband)
    c0, band, why = coarse(iq, sideband, rate)
    if c0 is None:
        return Tune(False, why=why, sideband=sideband, band=band)
    sign = 1.0 if sideband == "usb" else -1.0
    r = _assist(fine(iq, c0, sideband, _top(band), rate), iq, c0, sign, band, rate, edge=c0 + sign * LOW_CUT)
    common = dict(sideband=sideband, coarse=c0, band=band, voiced=r["voiced"], frames=r["frames"],
                  agree=r["agree"], rival=r["rival"], pitch=r["pitch"], details=r)
    if r["why"]:
        r["guesses"] = [c0 + sign * x for x in r.get("guesses") or []]
        return Tune(False, why=r["why"], **common)
    if r.get("alt") is not None:
        r["alt"] = c0 + sign * r["alt"]
    return Tune(True, offset=c0 + sign * r["delta"], **common)


# ------------------------------------------------------ listening until sure
class Listener:
    """Auto-tune that keeps listening until it is sure, or until `most`
    seconds have gone by.

    auto_tune() answers or refuses on one fixed capture. On real speech
    most of its refusals of a genuine voice were the frames not agreeing,
    the halves disagreeing or two offsets tying - each a shortage of
    voiced frames at different pitches, which more speech supplies. So
    the engine hands this everything heard so far, first after `first`
    seconds and then every `step`, and it answers as soon as the same
    tests auto_tune() applies pass on all of it; it refuses before the
    end only for what more listening cannot change (nothing there, not a
    voice).

    The frames already measured are kept (a few numbers each, see
    _pitches) and only the new ones are measured at each look, against
    the carrier the first look's spectrum put the voice at (the anchor);
    the voice's edge is measured again from all of it each time, since
    the comb's search is placed by it. A look costs the new audio's
    frames plus one pass over the votes - the receive thread never waits
    for it.

    Looking again and again is itself a risk: each look is another chance
    for the tests to pass by luck, and a long listen can hear two
    stations. Answering at the first look where auto_tune()'s tests
    passed took the 07/10/2026 recordings' leaked-carrier windows (c1,
    258 captures) from 117 right and 4 wrong to 194 right and 16 wrong.
    Every new wrong answer was a pitch (106-143 Hz) off, and came one of
    two ways, so two rules were added past the first look:

    - What was heard in each PART_SECONDS is judged by itself too, and
      every part must agree with the answer. The halves check alone let
      a listen through once the later speech outweighed the earlier: the
      first four seconds said one offset and the next eight another, and
      once the eight were most of the frames both halves said the later
      one. (A QSO partner a hundred hertz off, or one station's comb
      aliased in its first syllables: either way, not sure.)
    - The voice's edge, measured again at every look, is held at the
      nearest to the carrier side it has ever been (edge_lo). One station
      was refused at 4-6 s for a fit 137 Hz from the edge (MIN_EDGE_GAP),
      then answered at 7 s, a pitch off, when more audio moved the edge
      13 Hz further away: the rule should not weaken by being asked again.

    With both: 160 right, 4 wrong (the same 4 the first look gives, so
    the same as auto_tune()), 94 refused.

    That was still too trusting. On the labelled corpus c3 (194 labels,
    69 stations, from a 3 h recording), the comb answering alone at a
    later look gave 4 more right answers and 31 more wrong ones (on c1:
    30 and none - c1's truth is mostly one evening's few stations). So
    past the first look the comb must be confirmed: an answer needs the
    station's own leaked carrier to agree with it (_assist, `how`
    "line"). Without one, what the first look could not settle is
    refused at `most` seconds, saying the harmonics settled only later.
    Listening on thus waits for two independent measurements to agree,
    the voice's pitch harmonics and its carrier; it never trusts either
    alone where 4 s of the comb was not enough.

    The first look is still exactly auto_tune() on the same seconds."""

    def __init__(self, sideband: str, rate: float = RATE, first: float = CAPTURE_SECONDS,
                 step: float = LISTEN_STEP, most: float = LISTEN_SECONDS):
        self.sideband = sideband
        self.rate = rate
        self.first, self.step, self.most = first, step, most
        self.sign = 1.0 if sideband == "usb" else -1.0
        self.anchor: float | None = None     # the first look's coarse carrier, Hz from the dial
        self.coarse: float | None = None     # the latest look's
        self.band: tuple[float, float] | None = None
        self.nf = 0                          # frames measured
        self.env: list[np.ndarray] = []
        self.h = np.zeros(0)
        self.k = np.zeros(0, int)
        self.c = np.zeros((len(RAHMONICS), 0), complex)
        self.looked = 0                      # samples the last look had
        self.edge_lo: float | None = None    # the edge nearest the carrier any look measured
        self.result: Tune | None = None

    def due(self, n: int) -> bool:
        """Whether n samples heard call for a look now."""
        if self.result is not None:
            return False
        need = self.first if not self.looked else self.looked / self.rate + self.step
        return n >= min(need, self.most) * self.rate - 0.5

    def heard(self, n: int | None = None) -> float:
        return (self.looked if n is None else n) / self.rate

    def _hear(self, iq: np.ndarray) -> str:
        """Bring the measurement up to date with `iq` (everything heard
        since the start). Returns why it cannot go on, or ""."""
        self.looked = len(iq)
        c0, band, why = coarse(iq, self.sideband, self.rate)
        if self.anchor is None:
            if c0 is None:
                self.band = band
                return why
            self.anchor = self.coarse = c0
            self.band = band
            self._bins, fb = _bins(_top(band), self.rate)
            self._fb = fb
            self._combs = _combs(fb)
        elif c0 is not None and band[0] <= self.band[1] and band[1] >= self.band[0]:
            # The same voice, its edge measured on more of it. A refusal now
            # (a neighbour keyed up and the band grew too wide, the voice
            # stopped) or another signal leaves the last good edge standing.
            self.coarse, self.band = c0, band
        m = (len(iq) - FRAME) // HOP + 1 if len(iq) >= FRAME else 0
        if m > self.nf:
            a0, a1 = self.nf * HOP, (m - 1) * HOP + FRAME
            X, env = _ripple(_demod(iq[a0:a1], self.anchor, self.sideband, self.rate, a0), self._bins, self._fb)
            self.env.append(env)
            noise = np.percentile(np.concatenate(self.env), 25, axis=0)
            h, k, c = _pitches(_comb_frames(X, env, noise, self._combs))
            self.h = np.concatenate([self.h, h])
            self.k = np.concatenate([self.k, k])
            self.c = np.concatenate([self.c, c], axis=1)
            self.nf = m
        return ""

    def edge(self) -> float:
        """The voice's edge in audio Hz over the anchor: the nearest to the
        carrier any look has measured it (see the class's notes)."""
        e = LOW_CUT + self.sign * (self.coarse - self.anchor)
        self.edge_lo = e if self.edge_lo is None else min(self.edge_lo, e)
        return self.edge_lo

    def look(self, iq: np.ndarray) -> Tune | None:
        """Everything heard so far: the answer, a refusal, or None to keep
        listening. Once it has answered or refused it says the same again."""
        if self.result is not None:
            return self.result
        if self.sideband not in ("usb", "lsb"):
            self.result = Tune(False, why=f"auto-tune works on USB or LSB voice, not {self.sideband.upper()}",
                               sideband=self.sideband)
            return self.result
        # Whether this is a later look is which look it is, not how much it
        # holds: the engine looks once it has collected `first` seconds in
        # whole receive blocks, so its first look holds a little more
        # (4.05 s was typical). Judging that by its length made every
        # first look on air a later one - the comb alone could never
        # answer, and a voice without a leaked carrier was refused at 12 s
        # what auto_tune() answered at 4. listen(), which the corpora were
        # scored with, steps exactly to `first`, so it never saw this.
        later = self.looked > 0
        why = self._hear(iq)
        if why:
            # Nothing there, or not a voice: more of it will not change that.
            self.result = Tune(False, why=why, sideband=self.sideband, band=self.band)
            return self.result
        r = judge(self.h, self.k, self.c, self.edge(), part=int(PART_SECONDS * self.rate / HOP) if later else 0,
                  dial=(self.anchor, self.sign))
        r = _assist(r, iq, self.anchor, self.sign, self.band, self.rate,
                    edge=self.anchor + self.sign * self.edge_lo)
        r["heard"] = self.heard()
        common = dict(sideband=self.sideband, coarse=self.coarse, band=self.band, voiced=r["voiced"],
                      frames=r["frames"], agree=r["agree"], rival=r["rival"], pitch=r["pitch"], details=r)
        if not r["why"] and (not later or r.get("how") == "line"):
            if r.get("alt") is not None:
                r["alt"] = self.anchor + self.sign * r["alt"]
            self.result = Tune(True, offset=self.anchor + self.sign * r["delta"], **common)
        elif self.looked >= self.most * self.rate - 0.5:
            why = r["why"] or (f"the voice's harmonics settled on {self.anchor + self.sign * r['delta']:+.0f} Hz "
                               f"only after the first {self.first:.0f} s, and no leaked carrier confirmed it")
            g = r.get("guesses") or []
            if not r["why"]:
                g = [r["delta"]] + ([r["alt"]] if r.get("alt") is not None else [])
            r["guesses"] = [self.anchor + self.sign * x for x in g]
            r["guess"] = r["guesses"][0] if g else None
            self.result = Tune(False, why=why, **common)
        return self.result


def listen(iq: np.ndarray, sideband: str, rate: float = RATE, **kw) -> Tune:
    """A Listener run over a recording as the engine would run it on air:
    a look at `first` seconds and every `step` after, until it is sure or
    `most` seconds (or the recording) run out. The Tune's details say how
    long it listened (`heard`)."""
    lis = Listener(sideband, rate, **kw)
    n = 0
    while True:
        n = min(len(iq), n + int(lis.step * rate))
        if not lis.due(n) and n < len(iq):
            continue
        r = lis.look(iq[:n])
        if r is not None:
            return r
        if n >= len(iq):
            lis.most = n / rate
            return lis.look(iq[:n])
