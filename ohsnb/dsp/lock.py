"""Frequency locks: BeaconTracker (receive, rxCorr) and TxMonitor (transmit, txCorr).

Sign convention (DESIGN.md prose): rxCorr is how far *high* every signal
appears; the receiver tunes dl - lnbLo + rxCorr and displays apparent - rxCorr.
txCorr is added to the uplink so our signal lands on the dial.

BeaconTracker
-------------
Two stages, as the research recommends (docs/qo100-research.md, "Decisions"):

- **Search**: a 240 kHz channel around where each beacon should be, 1 s of
  it, one 240 000-point FFT (1 Hz bins). The lower beacon is found as the
  strongest pair of lines exactly 400 Hz apart (F1A: one of the two tones is
  always present, and an SSB station almost never shows two steady lines
  400 Hz apart); the middle beacon by squaring (BPSK has no carrier; its
  square has a line at twice the carrier). Search covers +-beaconSearchHz,
  enough for an unmodified LNB - but first +-2 kHz around a correction
  worth trusting (the stored one, the operator's, the last good one), and
  only then the whole range.
- **Not fooled**: squaring makes a line of anything with a carrier or a
  steady pitch, and the strongest line in a +-50 kHz window is often not
  the beacon (Ray, 05/10: SSB beside the middle beacon took the lock). A
  BPSK candidate is accepted only with the beacon's own traits - a 400 Hz
  symbol line in its envelope, no carrier, a steady level - and when the
  lower beacon is found it must agree with it; a single beacon from a full
  search must be seen twice in the same place (five times when far from
  where the beacon last was). What was refused, and why, is reported.
- **Track**: a 4 kHz channel centred on each beacon's expected position, a
  1 s window every 0.5 s. F1A: both tones' peaks (2 s of averaged spectra so
  key-up gaps don't hide the mark tone), midpoint - DJ0ABR's method. BPSK:
  squared-signal line /2. The loop is second order (error + drift rate), so
  a steadily warming LNB is followed with no standing error. A lock is
  taken at 10 dB and kept down to 6 (HOLD_SNR, hysteresis), so a weak
  beacon wandering round 10 dB is not lost and found every few seconds.

The chosen beacon steers rxCorr; when it is not heard (SNR too low) or what is
there is refused, the other one does - in the search as in tracking, at the
same floors (`_acquire_snr`). Both are measured whenever tracking, and their
difference is reported as a cross-check.

In Hold and Manual (the radio's beaconMode) the tracker only measures -
`measure()`: the beacons where the operator's correction says they are,
for the level guard and for the operator, changing nothing. BeaconFinder
is click-to-lock's one look at what the operator says is a beacon.

TxMonitor
---------
While keyed, we know exactly what we sent. Its power spectrum, delayed by the
round trip, is correlated against what *appeared* in the downlink since we
keyed (received spectrum over a baseline learnt while unkeyed) in a 200 kHz
channel around where it should land. The lag of the correlation peak is the
error. Wide (+-75 kHz, enough for a +-25 ppm Pluto at 2.4 GHz) until the
first lock, narrow (+-3 kHz) after, and corrections are only taken from
confident measurements (peak well clear of the correlation's noise).
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from ohscore.dsp.bank import Channel, Geometry
from ohscore.dsp.fir import _good_size

from .. import bandplan

HANN_ENBW = 1.5


def _parabolic(y: np.ndarray, k: int) -> float:
    """Fractional peak position around integer index k."""
    if k <= 0 or k >= len(y) - 1:
        return float(k)
    a, b, c = y[k - 1], y[k], y[k + 1]
    d = a - 2 * b + c
    return float(k) if d == 0 else k + 0.5 * (a - c) / d


def _psd(z: np.ndarray, nfft: int | None = None) -> np.ndarray:
    """fftshifted Hann power spectrum, normalised so a tone of amplitude A
    reads A**2 in its peak bin."""
    n = len(z)
    w, norm = _hann(n)
    X = np.fft.fft(z * w, nfft or n)
    return np.fft.fftshift(np.abs(X) ** 2) / norm


_HANN: dict[int, tuple[np.ndarray, float]] = {}


def _hann(n: int):
    if n not in _HANN:
        w = np.hanning(n + 2)[1:-1]
        _HANN[n] = (w, float(w.sum()) ** 2)
    return _HANN[n]


# -- what only the middle beacon has -------------------------------------------
# Squaring finds the suppressed carrier of *any* signal that has one, and
# makes lines out of anything steady enough: on 05/10 a loud SSB station a
# few kHz from the middle beacon took the lock off Ray (the simulator shows
# it: a station of steady vowels 12 dB over the beacon, 5.3 kHz away, wins
# the search every time - tests/test_lock.py). So a line in the squared
# spectrum is only a candidate. It is the beacon when the signal around it
# also has what the AO-40 format gives the beacon and nothing else on the
# band has (docs/qo100-research.md, "Middle beacon framing"):
#
# - a symbol-rate line: Manchester at 400 bit/s, lowpassed at 560 Hz, dips
#   in amplitude at every half-bit transition, so |x|^2 carries steady lines
#   at 400 and 800 Hz. Speech's envelope moves with its pitch, which never
#   holds one value to a hertz for a second; a carrier's has no lines.
# - no carrier: Manchester puts a null where the carrier would be, so little
#   of its power is within 100 Hz of the centre. A carrier, CW, PSK31 and
#   RTTY put most of theirs there.
# - a steady level: the beacon never pauses; speech is syllables and gaps.
#
# Thresholds from the simulator's beacon (which follows the spec) and its
# sustained-vowel voice, carriers, PSK31 and RTTY, measured each second for
# a minute: the beacon at 5 dB SNR (half the lock threshold) scored a
# symbol line of 26-28 dB, narrowness 0.04-0.06 and a swing of 0.4-1.2 dB;
# voice swung 5-29 dB (and now and then put a pitch harmonic on 400 or
# 800 Hz, a symbol line of up to 33 dB - which is why one trait is not
# enough); a carrier and PSK31 had narrowness 0.997 or more; RTTY 0.43-0.62
# with a symbol line of 10 dB at most. Every one of those was refused and
# every beacon second accepted.
SYMBOL_DB = 18.0      # symbol line over its neighbourhood, dB
NARROW_MAX = 0.5      # most power allowed within +-100 Hz of the centre
SWING_DB = 3.0        # most level change between tenths of a second, dB


def _bpsk_traits(Z: np.ndarray, bin_hz: float, err: float, noise_bin: float) -> dict:
    """The middle beacon's traits around a candidate carrier `err` Hz from
    the centre of the capture whose plain (unshifted, unwindowed) FFT is Z;
    `noise_bin` is that spectrum's noise per bin. Returns the three numbers
    and `why`, the reason it is not the beacon, or "" if it may be."""
    n = len(Z)
    K = int(round(1024 / bin_hz))
    rel = np.arange(-K, K)
    f = rel * bin_hz
    keep = np.abs(f) <= 800.0
    Zc = Z[(int(round(err / bin_hz)) + rel) % n] * keep
    excess = np.clip(np.abs(Zc) ** 2 - noise_bin, 0.0, None)
    narrow = float(excess[np.abs(f) <= 100.0].sum() / (excess[keep].sum() + 1e-30))
    # The candidate alone, +-800 Hz, back in time: 2K samples over the capture.
    y = np.fft.ifft(np.fft.ifftshift(Zc))
    env = np.abs(y) ** 2
    T = 1.0 / bin_hz
    E = np.abs(np.fft.rfft(env - env.mean())) ** 2

    def line(fz):
        k = int(round(fz * T))
        w = max(1, int(round(2 * T)))
        if k + w + 1 > len(E):
            return -99.0
        side = np.r_[E[int(fz * 0.6 * T):k - 5 * w], E[k + 5 * w + 1:int(fz * 1.4 * T)]]
        return 10 * math.log10(float(E[k - w:k + w + 1].max()) / (float(np.median(side)) + 1e-30) + 1e-30)

    symbol = max(line(400.0), line(800.0))
    m = len(env) // 10
    tenths = env[:m * 10].reshape(10, m).mean(axis=1)
    swing = 10 * math.log10(float(tenths.max()) / (float(tenths.min()) + 1e-30) + 1e-30)
    why = ""
    if narrow > NARROW_MAX:
        why = "a single line, not BPSK (a carrier, CW or PSK31)"
    elif symbol < SYMBOL_DB:
        why = "no 400 Hz symbol line (speech?)"
    elif swing > SWING_DB:
        why = f"level not steady, {swing:.0f} dB swing (speech?)"
    return {"symbol": round(symbol, 1), "narrow": round(narrow, 3), "swing": round(swing, 1), "why": why}


class _Beacon:
    def __init__(self, name: str, geo: Geometry):
        info = bandplan.BEACONS[name]
        self.name, self.kind, self.ref = name, info["kind"], info["ref"]
        self.shift = info.get("shift", 0.0)
        d = geo.decimation_for(4000.0)
        self.ch = Channel(geo, d)
        self.rate = self.ch.rate
        self.win = int(self.rate)            # 1 s
        self.buf = np.zeros(0, np.complex64)
        self.since = 0
        self.avg: np.ndarray | None = None
        self.last: dict | None = None
        ds = geo.decimation_for(240_000.0)
        self.sch = Channel(geo, ds)
        self.srate = self.sch.rate
        self.sbuf: list[np.ndarray] = []
        self.slen = 0

    def search_centre(self) -> float:
        # The 240 kHz channel sits on the space tone / carrier, so the search
        # is symmetric about where the beacon should be.
        return self.ref - (self.shift / 2 if self.kind == "f1a" else 0.0)


class BeaconTracker:
    UPDATE = 0.5          # seconds between tracking estimates
    LOCK_SNR = 10.0       # dB in 2.5 kHz to believe a measurement
    # Hysteresis. Once locked, the beacon being tracked keeps the lock down
    # to HOLD_SNR - but only a measurement that still has the middle
    # beacon's traits (_measure checks them from HOLD_SNR up) and lands
    # within MAX_TRACK_ERR of where the loop expects it. Acquiring, and
    # coming back from "lost", still need LOCK_SNR and everything the
    # search demands.
    # Why: Brian's dish, 07/10/2026, middle beacon at 8-10 dB. Played back
    # (13 min), every measurement had the beacon's traits by a wide margin
    # (symbol line 30-34 dB against 18, narrowness 0.03 against 0.5, swing
    # under 1.7 dB against 3) and an error of a few hertz, but the SNR sat
    # at 9.3-11.6 dB (median 9.8) - astride the one threshold. Three
    # readings under 10 dB (1.5 s) made it "lost", the next over 10 made
    # it "locked": 197 flips, locked 56 % of the time, and while "lost"
    # rxCorr stood still as the LNB drifted on (2.5 Hz/s), so each relock
    # jumped up to 40 Hz. 6 dB: the simulator's beacon at 5 dB still
    # shows all three traits clearly (see SYMBOL_DB above), so what is
    # held is still known to be the beacon; under it the readings are too
    # few hertz from noise to steer by.
    HOLD_SNR = 6.0
    MAX_TRACK_ERR = 60.0  # Hz: a bigger jump while locked is an outlier, not drift
    # The narrow search: +-2 kHz around the correction already held. Used
    # first whenever there is one worth trusting - after the operator has
    # said where the beacon is (click-to-lock, rxCorr typed or nudged), on
    # returning to Auto from Hold or Manual, after losing the beacon, and
    # at start from the stored correction - so a beacon that is where it
    # was is found again before anything further away is even looked at.
    TIGHT_HZ = 2_000.0
    NARROW_START = 3      # narrow searches (~1 s each) before widening, from a stored or resumed correction
    NARROW_HAND = 30      # ... after the operator said where the beacon is: half a minute on their word
    # A single beacon found by a full-width search must be seen in the same
    # place this many times running before it is locked to (both beacons
    # found and agreeing need no wait), and more often when it is far from
    # where the beacon last was: the real beacon does not jump, so a sudden
    # far candidate is far more likely a station than the LNB.
    CONFIRM = 2
    CONFIRM_FAR = 5
    FAR_HZ = 500.0
    CONFIRM_TOL = 30.0
    # The narrow search took a single beacon at its first sighting until
    # 17/10/2026. On ohs-box that day, with the LNB's LO hopping (UNSTEADY_N
    # below), every loss was followed by a narrow search that locked to
    # wherever the beacon happened to be for that second - six times in
    # three minutes, rxCorr moving up to 1.9 kHz each time and taking the
    # receive and transmit dials with it - and lost it again a second or two
    # later. So the narrow search asks for CONFIRM sightings too (not
    # CONFIRM_FAR: it is looking where the beacon was), which costs a steady
    # beacon one more second to come back. Except when the operator has
    # just said where the beacon is (`trusted`, NARROW_HAND): their word is
    # the confirmation.
    # Furthest from DC (fraction of fs) a beacon can be looked for: past it
    # is the SDR's filter skirt and then the other side of Nyquist. Matters
    # only at 600 kS/s, where the lower beacon is already 246 kHz from DC.
    USABLE = 0.45
    DC_HZ = 250.0         # a refused candidate this close to DC is the SDR's own spur
    # A beacon that will not stay in one place. On 17/10/2026, after the
    # Bullseye LNB on ohs-box had been power-cycled and switched 13/18 V a
    # few times, its LO came up ~35 kHz from where it had been all morning
    # and would not hold still there: beacon lock took the middle beacon at
    # 18-22 dB and lost it within a second or two, for over an hour; the
    # half-second readings landed up to 600 Hz apart, and six locks in three
    # minutes spread over 1.9 kHz. Reconnected, the LO came up in its usual
    # state and held: a 46 s recording of that (10-12 dB) reads the beacon
    # 2.8 Hz from one half-second to the next (median; 10 Hz at most). The
    # lock was right not to steer by it - nothing can, to the few hertz
    # digital modes need - but all it said was "no 400 Hz symbol line
    # (speech?)", which sent everyone looking for a station on the beacon.
    # So the beacon's own readings are watched: of the steps between
    # UNSTEADY_N consecutive ones (heard at LOCK_SNR or more, whether or not
    # they passed the traits test - a smeared beacon fails it), UNSTEADY_K
    # or more over UNSTEADY_HZ is an unsteady beacon, and is said to be,
    # here and in the searches for UNSTEADY_HOLD s after. 100 Hz is ten
    # times the good recording's worst step and nine times the simulator's
    # 22 Hz/s wander's, and a third of the bad period's median step. A
    # count, not the median: an LO that hops every second or so and sits
    # still between (the simulator's, 300 Hz every 1.5 s, loses the lock
    # as surely) has a median step of nothing. Three of eleven, not one or
    # two: a stray reading - a station crossing the channel - is two big
    # steps, out and back. The readings are where the beacon was heard,
    # not where the loop had it, so they are kept across searches (up to
    # UNSTEADY_SPAN s for the lot: a 2 Hz/s LNB moves 60 Hz in 30 s).
    UNSTEADY_N = 12
    UNSTEADY_K = 3
    UNSTEADY_SPAN = 30.0
    UNSTEADY_HZ = 100.0
    UNSTEADY_HOLD = 60.0
    UNSTEADY_WHY = "beacon unsteady in frequency - check the LNB and its supply"

    def __init__(self, geo: Geometry, choice: str = "middle", search_hz: float = 50_000.0, rx_corr: float = 0.0,
                 narrow: int = 0):
        self.geo = geo
        self.choice = choice
        self.search_hz = search_hz
        self.rx_corr = float(rx_corr)
        self.rate_hz_s = 0.0
        self.state = "searching"
        self.beacons = {n: _Beacon(n, geo) for n in ("middle", "lower")}
        self.err = 0.0
        self.snr = 0.0
        self.level_db = -200.0
        self.level_lin = 0.0
        self.used = ""
        self.held = ""                  # the beacon the lock is on, while locked (HOLD_SNR applies to it)
        self.cross = None
        self.bad = 0
        self.lost_since = None
        self.t = 0.0
        self.hist = deque(maxlen=64)   # (t, rx_corr) to undo the loop's own moves within a window
        self.enabled = True
        self.narrow_left = int(narrow)
        self.trusted = False                            # the narrow search is on the operator's word
        self.narrow_extra = False                       # the narrow search has had its one extra round
        self.window = self.search_hz
        self.pending: tuple[float, int] | None = None   # (error, sightings) awaiting confirmation
        self.locked_at: float | None = None             # rx_corr when last locked
        self.rejected: list[str] = []                   # why the last look refused what it saw
        self.why = ""                                   # the latest of those, kept until a lock
        self.seen: dict[str, deque] = {}               # (t, where) each beacon was heard, UNSTEADY_N of them
        self.unsteady_t: float | None = None            # when the beacon was last found unsteady

    # The radio tells the tracker where DC is each block.
    def _offset(self, dl: float, rx_if: float, lnb_lo: float) -> float:
        return dl - lnb_lo + self.rx_corr - rx_if

    def reset(self, rx_corr: float | None = None, narrow: int = 0, trusted: bool = False):
        """Search again, from `rx_corr` (default: the current correction),
        `narrow` rounds at +-TIGHT_HZ before the full range; `trusted`: the
        operator has just said where the beacon is (CONFIRM_TOL above)."""
        if rx_corr is not None:
            self.rx_corr = float(rx_corr)
        self.state = "searching"
        self.held = ""
        self.rate_hz_s = 0.0
        self.narrow_left = int(narrow)
        self.trusted = bool(trusted) and narrow > 0
        self.narrow_extra = False
        self.pending = None
        for b in self.beacons.values():
            b.buf = np.zeros(0, np.complex64)
            b.avg = None
            b.sbuf, b.slen = [], 0

    def process(self, X: np.ndarray, starts: np.ndarray, rx_if: float, lnb_lo: float, t: float) -> dict | None:
        """Feed one block of analysis frames. Returns a lock report when an
        estimate was made (every UPDATE s while tracking, every ~1 s while
        searching), else None."""
        if not self.enabled or X.shape[0] == 0:
            return None
        self.t = t
        self.hist.append((t, self.rx_corr))
        if self.state == "searching":
            return self._search(X, starts, rx_if, lnb_lo)
        return self._track(X, starts, rx_if, lnb_lo)

    # -- search ---------------------------------------------------------------
    def _search(self, X, starts, rx_if, lnb_lo):
        done = True
        for b in self.beacons.values():
            b.sch.set_freq(self._offset(b.search_centre(), rx_if, lnb_lo))
            y = b.sch.take(X, starts)
            b.sbuf.append(y)
            b.slen += len(y)
            if b.slen < int(b.srate):
                done = False
        if not done:
            return None
        narrow = self.narrow_left > 0
        win = self.TIGHT_HZ if narrow else self.search_hz
        self.window = win
        self.rejected = []
        found = {}
        for name, b in self.beacons.items():
            z = np.concatenate(b.sbuf)[-int(b.srate):]
            b.sbuf, b.slen = [], 0
            # Only as far as the SDR still sees: errors that would put the
            # beacon past USABLE x fs from DC are not searched.
            off = self._offset(b.search_centre(), rx_if, lnb_lo)
            u = self.USABLE * self.geo.fs - 2000.0
            lo, hi = max(-win, -u - off), min(win, u - off)
            if hi - lo < 1000.0:
                continue
            r = self._search_one(b, z, lo, hi, dc=-off)
            if r:
                found[name] = r
        mid, low = found.get("middle"), found.get("lower")
        agree = None
        if mid and low:
            agree = next((c for c in mid if abs(c["err"] - low[0]["err"]) < 50), None)
            if agree is None and low[0]["snr"] > 18:
                # The beacons are a fixed distance apart: a middle-beacon
                # candidate the lower beacon contradicts is something else.
                for c in mid:
                    self._reject(f"middle at {bandplan.mhz(self.beacons['middle'].ref + c['err'], 4)}: "
                                 f"disagrees with the lower beacon by {(c['err'] - low[0]['err']) / 1000:+.1f} kHz")
                del found["middle"]
                mid = None
        report = {"state": "searching", "rxCorr": self.rx_corr, "window": win, "narrow": narrow,
                  "found": {k: round(v[0]["err"], 1) for k, v in found.items()}}
        pick, name = None, ""
        if agree is not None:
            pick, name = (agree, "middle") if self.choice == "middle" else (low[0], "lower")
        else:
            # One beacon alone: the chosen one when it is heard well enough
            # to steer by, else the other - the fall-back the tracker makes
            # too, with the same floors as tracking (_acquire_snr). These
            # were 15 dB for the chosen beacon and 18 for the other until
            # 13/10/2026, which never bit on the middle beacon (its search
            # SNR was measured against a noise floor the window's filter
            # had zeroed, and read ~140 dB) and held the lower one to 8 dB
            # more than tracking asks: on the simulator with both beacons
            # 10 dB down, the lower one read ~13 dB, was found in the right
            # place every second and never taken, so with the middle beacon
            # gone nothing locked. (Brian's dish on 12/10 read the middle
            # beacon at 10-13 dB and the lower at 0-8: there the lower one
            # is too weak to fall back to at all, and is now said to be.)
            heard = {}
            for k, v in found.items():
                need = self._acquire_snr(k)
                if v[0]["snr"] >= need:
                    heard[k] = v[0]
                elif v[0]["snr"] > 0.0:
                    # Under 0 dB is not worth a word: the F1A search finds
                    # its best tone pair in plain noise at about -21 dB.
                    self._reject(f"{k} at {bandplan.mhz(self.beacons[k].ref + v[0]['err'], 4)}: "
                                 f"{v[0]['snr']:.1f} dB, too weak to lock to (needs {need:g})")
            name = self.choice if self.choice in heard else next(iter(heard), "")
            pick = heard.get(name)
        seen = pick is not None
        if pick and agree is None and not (narrow and self.trusted):
            pick = self._confirmed(pick["err"], far_ok=narrow) and pick
            if not pick:
                report["confirming"] = True
        if pick:
            wide = not narrow
            self.rx_corr += pick["err"]
            self.state = "locked"
            self.held = name
            self.bad = 0
            self.lost_since = None
            self.locked_at = self.rx_corr
            self.pending = None
            self.narrow_left = 0
            self.trusted = False
            self.why = ""
            self.hist.clear()
            for b in self.beacons.values():
                b.buf = np.zeros(0, np.complex64)
                b.avg = None
                b.since = 0
            report.update(state="locked", rxCorr=self.rx_corr, acquired=round(pick["err"], 1), wide=wide)
        elif narrow:
            self.narrow_left -= 1
            if self.narrow_left == 0 and report.get("confirming") and not self.narrow_extra:
                # Seen once in the last narrow round: one more, for the
                # second sighting it now needs (CONFIRM_TOL above) - a
                # beacon coming back late in the narrow rounds would
                # otherwise be left to the wide search, which a louder
                # station can win. Once only, or a hopping beacon would
                # keep the search narrow for ever.
                self.narrow_left, self.narrow_extra = 1, True
            if self.narrow_left == 0:
                report["widened"] = True
        if not seen and not self.rejected:
            # Nothing at all: say so, rather than leave the last refusal
            # standing. On 13/10/2026 the LNB's signal stopped reaching the
            # Pluto, and for hours the only reason shown was a refused
            # "middle at 10489.7465" - the receiver's own DC spur - which
            # read as a station sitting on the beacon.
            self.why = f"no beacon heard within +-{win / 1000:g} kHz"
        if not pick and self.unsteady_t is not None and self.t - self.unsteady_t < self.UNSTEADY_HOLD:
            # Tracking has just seen the beacon wander: a smeared beacon
            # fails the traits test here too, and "speech?" is the wrong
            # thing to send the operator looking for (UNSTEADY_N above).
            # What was refused is still in `rejected`.
            self.why = self.UNSTEADY_WHY
        report["rejected"] = list(self.rejected)
        return report

    def _acquire_snr(self, name: str) -> float:
        """The SNR a beacon found alone by the search needs to be locked to:
        the middle beacon's candidates have already passed its traits test,
        which holds down to HOLD_SNR (see there), so that is enough; the
        lower beacon has no such test (two lines 400 Hz apart is all it
        is), so it needs LOCK_SNR, as tracking asks before taking it over."""
        return self.HOLD_SNR if name == "middle" else self.LOCK_SNR

    def _confirmed(self, err: float, far_ok: bool = False) -> bool:
        """A search's single-beacon find: true once it has been seen in
        the same place enough times running (CONFIRM_FAR when far from
        where the beacon last was, unless `far_ok`: the narrow search)."""
        if self.pending is not None and abs(self.pending[0] - err) <= self.CONFIRM_TOL:
            self.pending = (err, self.pending[1] + 1)
        else:
            self.pending = (err, 1)
        far = not far_ok and self.locked_at is not None and abs(self.rx_corr + err - self.locked_at) > self.FAR_HZ
        return self.pending[1] >= (self.CONFIRM_FAR if far else self.CONFIRM)

    def _reject(self, why: str):
        if len(self.rejected) < 4:
            self.rejected.append(why)
        self.why = why

    def _search_one(self, b: _Beacon, z: np.ndarray, lo_hz: float, hi_hz: float, dc: float | None = None):
        """The beacon in a 1 s, 240 kHz capture centred on its expected
        position, searched for errors from lo_hz to hi_hz: a list of
        candidates {err, snr}, best first (F1A: just the best), or None.
        `dc`: the error at which a candidate would sit on the receiver's
        own centre."""
        n = len(z)
        rate = b.srate
        bin_hz = rate / n
        edge = rate * 0.42 - 2000
        mid = n // 2
        if b.kind == "f1a":
            lo_k, hi_k = int(max(lo_hz, -edge) / bin_hz), int(min(hi_hz, edge) / bin_hz)
            P = _psd(z)
            sh = int(round(b.shift / bin_hz))
            # Smooth over +-2 bins: the tones wander a little within the second.
            Ps = np.convolve(P, np.ones(5) / 5, mode="same")
            lo, hi = mid + lo_k, mid + hi_k
            score = np.minimum(Ps[lo:hi], Ps[lo + sh:hi + sh])
            k = int(np.argmax(score))
            noise = float(np.median(P)) + 1e-30
            snr = 10 * math.log10(score[k] / noise + 1e-30) - 10 * math.log10(2500 / bin_hz)
            if 10 * math.log10(score[k] / noise + 1e-30) < 12:
                return None
            return [{"err": (lo + k - mid) * bin_hz, "snr": snr}]
        # BPSK: a line at 2x the carrier in the squared signal (2x the error,
        # so the window is twice as wide there). First, everything outside
        # the window is removed: squared, the channel's +-100 kHz becomes
        # +-200 kHz, which folds back over the +-120 kHz a 240 kHz channel
        # holds, and a signal 70-100 kHz out came back as a line inside a
        # +-50 kHz search. Limited like this, the squared window stays
        # inside Nyquist up to rate/4 (58 kHz at 1.2 MS/s).
        lim = rate / 4 - 2500.0
        lo_hz, hi_hz = max(lo_hz, -lim), min(hi_hz, lim)
        Z = np.fft.fft(z)
        fz = np.fft.fftfreq(n, 1 / rate)
        noise_bin = float(np.median(np.abs(Z) ** 2)) + 1e-30
        zm = np.fft.ifft(Z * ((fz >= lo_hz - 1500) & (fz <= hi_hz + 1500))).astype(np.complex64)
        P2 = _psd(zm * zm)
        lo, hi = mid + int(2 * lo_hz / bin_hz), mid + int(2 * hi_hz / bin_hz)
        seg = P2[lo:hi].copy()
        noise = float(np.median(seg)) + 1e-30
        # SNR from the capture as it came, not from zm: zm's spectrum is
        # zero outside the window, more than half of it at the usual
        # +-50 kHz, so its median - the noise - was zero and every
        # candidate read ~140 dB, whatever it was.
        P = _psd(z)
        out = []
        # Each candidate looked at takes its neighbourhood out of the
        # running: a line just its own +-150 Hz, a refused broad signal (a
        # voice) its whole 3 kHz - a voice makes a dozen squared lines, and
        # without that they used up every look before the beacon's turn.
        # The beacon's guard band is 5 kHz, so 1.5 kHz either side of a
        # voice never reaches it.
        for _ in range(8):
            k = int(np.argmax(seg))
            if 10 * math.log10(seg[k] / noise + 1e-30) < 18:
                break
            kk = _parabolic(P2, lo + k)
            err = (kk - mid) * bin_hz / 2
            snr = self._bpsk_snr(P, bin_hz, err)
            tr = _bpsk_traits(Z, bin_hz, err, noise_bin)
            broad = tr["why"] and tr["narrow"] <= NARROW_MAX
            guard = int(2 * (1500.0 if broad else 150.0) / bin_hz)
            seg[max(0, k - guard):k + guard + 1] = 0.0
            if tr["why"]:
                # Refused at the receiver's own centre is the SDR's DC spur
                # (a Pluto's sits ~10 dB over the noise when no signal
                # arrives), not a signal worth naming: on 13/10/2026 it was
                # the only "candidate" for hours, and read as a station on
                # the beacon. A beacon that is there is still looked at.
                at_dc = dc is not None and abs(err - dc) < self.DC_HZ
                if snr > 10 and not at_dc:
                    self._reject(f"middle at {bandplan.mhz(b.ref + err, 4)}: {tr['why']}")
                continue
            out.append({"err": err, "snr": snr, **tr})
            if len(out) >= 3:
                break
        return out or None

    @staticmethod
    def _bpsk_snr(P: np.ndarray, bin_hz: float, err: float) -> float:
        mid = len(P) // 2 + int(round(err / bin_hz))
        w = int(900 / bin_hz)
        sig = P[mid - w:mid + w].sum()
        noise = float(np.median(P)) + 1e-30
        excess = max(sig - noise * 2 * w, 1e-30)
        return 10 * math.log10(excess / (noise * 2500 / bin_hz))

    # -- track ----------------------------------------------------------------
    def _collect(self, X, starts, rx_if, lnb_lo):
        """Each beacon's 4 kHz channel where the correction says it is; every
        UPDATE s, a measurement of each ({name: {err, snr, power}}), else
        None."""
        due = False
        for b in self.beacons.values():
            b.ch.set_freq(self._offset(b.ref, rx_if, lnb_lo))
            y = b.ch.take(X, starts)
            b.buf = np.concatenate([b.buf, y])[-b.win:]
            b.since += len(y)
            if b.since >= self.UPDATE * b.rate and len(b.buf) >= b.win:
                due = True
        if not due:
            return None
        meas = {}
        for name, b in self.beacons.items():
            if b.since < self.UPDATE * b.rate or len(b.buf) < b.win:
                continue
            b.since = 0
            m = self._measure(b)
            if m is not None:
                # The window spans corrections this loop already made; what it
                # measured is relative to the average correction over it.
                window = [c for (tt, c) in self.hist if tt >= self.t - 1.0]
                if window:
                    m["err"] -= self.rx_corr - float(np.mean(window))
                b.last = m
                meas[name] = m
        return meas

    def measure(self, X: np.ndarray, starts: np.ndarray, rx_if: float, lnb_lo: float, t: float,
                rx_corr: float) -> dict | None:
        """Hold and Manual: the beacons measured where the correction held
        (`rx_corr`, the operator's) says they are, and nothing changed.
        The beacon's level is what the level guard judges our downlink by,
        so it must go on being measured whoever sets rxCorr; and the error
        - how far the beacon has drifted from where it is held - is what
        the operator nudging rxCorr by hand needs to see. A report of
        state "held" every UPDATE s, else None."""
        if X.shape[0] == 0:
            return None
        if rx_corr != self.rx_corr:
            # Moved by hand: a window straddling the move would average two
            # positions, and F1A's 2 s average two more.
            self.rx_corr = float(rx_corr)
            for b in self.beacons.values():
                b.buf = np.zeros(0, np.complex64)
                b.avg = None
                b.since = 0
        self.t = t
        self.hist.append((t, self.rx_corr))
        meas = self._collect(X, starts, rx_if, lnb_lo)
        if meas is None:
            return None
        good = {k: v for k, v in meas.items() if v["snr"] >= self.LOCK_SNR}
        use = self.choice if self.choice in good else next(iter(good), None)
        self.cross = (round(meas["middle"]["err"] - meas["lower"]["err"], 1)
                      if "middle" in good and "lower" in good else None)
        self.used = use or ""
        self.rate_hz_s = 0.0
        if use is not None:
            m = good[use]
            self.err, self.snr = m["err"], m["snr"]
            self.level_lin = m["power"]
            self.level_db = 10 * math.log10(m["power"] + 1e-30)
        return {**self._report(meas), "state": "held"}

    def _floor(self, name: str) -> float:
        """The SNR a measurement of beacon `name` needs to steer: while
        locked, HOLD_SNR for the beacon the lock is on and for the middle
        beacon (every reading of which from HOLD_SNR up has passed its
        traits test, so it may take the lock back after a fall-back to the
        lower one); LOCK_SNR otherwise. The lower beacon has no such test,
        so it is never taken over to at less than LOCK_SNR."""
        if self.state == "locked" and name in (self.held, "middle"):
            return self.HOLD_SNR
        return self.LOCK_SNR

    def _steady(self, meas: dict) -> None:
        """Note where each beacon was heard (UNSTEADY_N above), and say so
        when the one being steered by will not keep still."""
        for name, m in meas.items():
            if m.get("heard", m["snr"]) >= self.LOCK_SNR:
                # setdefault: ohsnb.analyse adds the upper beacon after construction.
                self.seen.setdefault(name, deque(maxlen=self.UNSTEADY_N)).append((self.t, self.rx_corr + m["err"]))
        big = {}
        for name, q in self.seen.items():
            if len(q) == q.maxlen and q[-1][0] - q[0][0] <= self.UNSTEADY_SPAN:
                where = np.array([w for _, w in q])
                big[name] = int(np.sum(np.abs(np.diff(where)) > self.UNSTEADY_HZ))
        if not big:
            return
        if max(big.values()) >= self.UNSTEADY_K:
            self.unsteady_t = self.t
            self.why = self.UNSTEADY_WHY
        elif max(big.values()) == 0 and self.why == self.UNSTEADY_WHY:
            # Steady again, for UNSTEADY_N readings running - not merely
            # under the count, or the reason would come and go with each
            # hop leaving the window.
            self.unsteady_t = None
            self.why = ""

    def _track(self, X, starts, rx_if, lnb_lo):
        meas = self._collect(X, starts, rx_if, lnb_lo)
        if meas is None:
            return None
        self._steady(meas)
        good = {k: v for k, v in meas.items() if v["snr"] >= self._floor(k)}
        use = self.choice if self.choice in good else next(iter(good), None)
        self.cross = (round(meas["middle"]["err"] - meas["lower"]["err"], 1)
                      if "middle" in good and "lower" in good else None)
        dt = self.UPDATE
        if use is None or abs(good[use]["err"]) > self.MAX_TRACK_ERR:
            self.bad += 1
            if self.bad >= 3 and self.state == "locked":
                self.state = "lost"
                self.lost_since = self.t
            if self.state == "lost" and self.t - (self.lost_since or self.t) > 10.0:
                # Look where it was first: a beacon that faded comes back
                # where it went, and a wide search is what a loud station
                # nearby can win.
                self.reset(narrow=self.NARROW_START)
            self.used = ""
            return self._report(meas)
        m = good[use]
        self.used = self.held = use
        self.bad = 0
        self.state = "locked"
        self.lost_since = None
        e = m["err"]
        self.err, self.snr = e, m["snr"]
        self.level_lin = m["power"]
        self.level_db = 10 * math.log10(m["power"] + 1e-30)
        # Second-order loop: proportional on the error, integral on the
        # drift rate, so a steadily warming LNB leaves no standing error.
        # Gains chosen by sweeping against the simulator's LNB wandering at up
        # to 22 Hz/s (far faster than a real one): 0.5/0.25 held it within
        # 3.6 Hz; predicting the window's 0.5 s lag forward made it worse
        # (the history correction above already accounts for the loop's moves).
        self.rate_hz_s += 0.25 * e / dt
        self.rate_hz_s = max(-200.0, min(200.0, self.rate_hz_s))
        self.rx_corr += 0.5 * e + self.rate_hz_s * dt
        self.locked_at = self.rx_corr
        return self._report(meas)

    def _report(self, meas):
        # "stream": the receive stream's clock (seconds of samples) the
        # report was made at. The "t" the radio adds when publishing is the
        # wall clock, which says nothing about where in the signal the
        # estimate belongs; a drifting LNB's truth has to be read at this
        # time, not at whatever the device's clock has reached by the time
        # someone looks (on a fast machine running the simulator unpaced,
        # that is seconds of signal later).
        return {"state": self.state, "stream": round(self.t, 3), "rxCorr": self.rx_corr, "err": round(self.err, 2),
                "rate": round(self.rate_hz_s, 3),
                "snr": round(self.snr, 1), "used": self.used, "level": round(self.level_db, 1),
                "cross": self.cross, "rejected": [v["why"] for v in meas.values() if v.get("why")],
                "beacons": {k: {"err": round(v["err"], 2), "snr": round(v["snr"], 1)} for k, v in meas.items()}}

    def _measure(self, b: _Beacon) -> dict | None:
        z = b.buf
        nfft = 2 * len(z)                      # zero-pad: 0.5 Hz bins before interpolation
        bin_hz = b.rate / nfft
        mid = nfft // 2
        if b.kind == "f1a":
            P = _psd(z, nfft)
            # Average 2 s so key-up gaps don't hide one tone.
            b.avg = P if b.avg is None else 0.5 * b.avg + 0.5 * P
            P = b.avg
            half = int(round(b.shift / 2 / bin_hz))
            rng_ = int(150 / bin_hz)
            noise = float(np.median(P)) + 1e-30
            peaks = []
            for c in (mid - half, mid + half):
                seg = P[c - rng_:c + rng_]
                k = int(np.argmax(seg))
                peaks.append((_parabolic(P, c - rng_ + k), seg[k]))
            (k1, p1), (k2, p2) = peaks
            both = min(p1, p2) / noise > 10 ** 1.2
            if both:
                err = ((k1 + k2) / 2 - mid) * bin_hz
                pk = max(p1, p2)
            else:
                # Only one tone in the window: it is whichever is nearer.
                k, pk = (k1, p1) if p1 >= p2 else (k2, p2)
                err = (k - (mid - half if p1 >= p2 else mid + half)) * bin_hz
            snr = 10 * math.log10(pk / noise + 1e-30) - 10 * math.log10(2500 / (b.rate / len(z)))
            # F1A is constant-envelope: its power is the tone power(s).
            power = (p1 + p2) if both else pk
            return {"err": err, "snr": snr, "power": power}
        P2 = _psd(z * z, nfft)
        w = int(round(1800 / bin_hz))
        seg = P2[mid - w:mid + w]
        k = int(np.argmax(seg))
        noise2 = float(np.median(P2)) + 1e-30
        if seg[k] / noise2 < 10 ** 1.5:
            return {"err": 0.0, "snr": -99.0, "power": 0.0}
        kk = _parabolic(P2, mid - w + k)
        err = (kk - mid) * bin_hz / 2
        P = _psd(z)
        bh = b.rate / len(z)
        snr = self._bpsk_snr(P, bh, err)
        # The same test as the search: what is in the window must still be
        # the beacon. Something else drifting into the 4 kHz channel - a
        # station in the guard band - would otherwise be followed off it.
        Z = np.fft.fft(z)
        tr = _bpsk_traits(Z, bh, err, float(np.median(np.abs(Z) ** 2)) + 1e-30)
        # From HOLD_SNR, not LOCK_SNR: a reading in the hysteresis band
        # keeps a lock only if it is still the beacon.
        if tr["why"] and snr >= self.HOLD_SNR:
            why = f"middle at {bandplan.mhz(b.ref + err, 4)}: {tr['why']}"
            self.why = why
            # `heard`: refused, but how loud - an unsteady beacon is heard
            # well and refused, and _steady needs to know where.
            return {"err": err, "snr": -99.0, "power": 0.0, "why": why, "heard": snr}
        c = len(P) // 2 + int(round(err / bh))
        wb = int(900 / bh)
        power = max(P[c - wb:c + wb].sum() - float(np.median(P)) * 2 * wb, 0.0) / HANN_ENBW
        return {"err": err, "snr": snr, "power": power}


class BeaconFinder:
    """Click-to-lock: one look, a second long, at what the operator says is
    a beacon, to find its exact centre near the click. The operator clicks
    *roughly* on it - the scope's pixels are tens of hertz wide and the
    middle beacon is a 1 kHz hump with no line at its centre - so the
    reference is searched for within SNAP_HZ of the click: the BPSK beacon
    by squaring (checked for being the beacon, as the tracker checks), an
    F1A beacon by its two tones 400 Hz apart. `feed()` returns the result
    once: {"found": bool, "offset": Hz from the click to the beacon's
    reference, "why": what was or was not seen}.

    Works in absolute IF (the click's apparent frequency at the moment of
    the click), so neither the tracker moving rxCorr meanwhile nor the
    receiver re-centring disturbs it."""

    SNAP_HZ = 500.0
    SECONDS = 1.0

    def __init__(self, geo: Geometry, name: str, apparent_if: float):
        info = bandplan.BEACONS[name]
        self.name, self.kind, self.shift = name, info["kind"], info.get("shift", 0.0)
        self.apparent = float(apparent_if)
        # 8 kHz: the squared +-1 kHz window and the beacon's +-800 Hz
        # around a candidate both fit with room; nothing aliases into them.
        self.ch = Channel(geo, geo.decimation_for(8000.0))
        self.rate = self.ch.rate
        self.bufs: list[np.ndarray] = []
        self.n = 0

    def feed(self, X: np.ndarray, starts: np.ndarray, rx_if: float) -> dict | None:
        self.ch.set_freq(self.apparent - rx_if)
        y = self.ch.take(X, starts)
        self.bufs.append(y)
        self.n += len(y)
        if self.n < int(self.rate * self.SECONDS):
            return None
        z = np.concatenate(self.bufs)[-int(self.rate * self.SECONDS):]
        return self._f1a(z) if self.kind == "f1a" else self._bpsk(z)

    def _bpsk(self, z):
        n = len(z)
        bin_hz = self.rate / n
        mid = n // 2
        P2 = _psd(z * z)
        w = int(2 * self.SNAP_HZ / bin_hz)
        seg = P2[mid - w:mid + w + 1]
        k = int(np.argmax(seg))
        noise = float(np.median(P2)) + 1e-30
        if 10 * math.log10(seg[k] / noise + 1e-30) < 18:
            return {"found": False, "offset": 0.0, "why": "no BPSK beacon within 500 Hz of the click"}
        err = (_parabolic(P2, mid - w + k) - mid) * bin_hz / 2
        Z = np.fft.fft(z)
        tr = _bpsk_traits(Z, bin_hz, err, float(np.median(np.abs(Z) ** 2)) + 1e-30)
        if tr["why"]:
            return {"found": False, "offset": 0.0, "why": f"what is there is {tr['why']}"}
        return {"found": True, "offset": err, "why": "the BPSK beacon's centre"}

    def _f1a(self, z):
        n = len(z)
        bin_hz = self.rate / n
        mid = n // 2
        P = _psd(z)
        Ps = np.convolve(P, np.ones(5) / 5, mode="same")
        half = int(round(self.shift / 2 / bin_hz))
        w = int(self.SNAP_HZ / bin_hz)
        # The pair's midpoint anywhere within SNAP_HZ of the click.
        c = np.arange(mid - w, mid + w + 1)
        score = np.minimum(Ps[c - half], Ps[c + half])
        k = int(np.argmax(score))
        noise = float(np.median(P)) + 1e-30
        if 10 * math.log10(score[k] / noise + 1e-30) < 12:
            return {"found": False, "offset": 0.0, "why": "no pair of tones 400 Hz apart within 500 Hz of the click"}
        return {"found": True, "offset": (c[k] - mid) * bin_hz, "why": "the midpoint of its two tones"}

class TxMonitor:
    """See the module docstring. The radio feeds it:

    - `rx(y, t_end)`: the monitor channel's samples (centred on where our
      dial should land, 200 kHz), with the stream time of the last sample;
    - `tx(bb, t_air)`: the 12 kHz complex baseband we transmitted, relative
      to the TX dial, with the stream time its first sample went on air.

    `step()` results (dicts) come back from `rx()` when a measurement is made.
    """

    FRAME = 0.1          # s per spectrum frame -> 10 Hz bins
    WINDOW = 10          # frames per measurement (1 s)
    WIDE = 75_000.0
    NARROW = 3_000.0
    CONFIDENT = 8.0      # peak above correlation noise (robust z-score)

    def __init__(self, geo: Geometry, rtt: float = 0.25, trusted: bool = False):
        d = geo.decimation_for(200_000.0)
        self.ch = Channel(geo, d)
        self.rate = self.ch.rate
        self.F = int(round(self.rate * self.FRAME))
        self.bin_hz = self.rate / self.F
        self.tx_rate = 12_000.0
        self.tF = int(round(self.tx_rate * self.FRAME))
        self.rtt = rtt
        self.trusted = trusted
        self.buf = np.zeros(0, np.complex64)
        self.buf_t0 = 0.0                 # stream time of buf[0]
        self.baseline: np.ndarray | None = None
        self.tx_hist: deque = deque()     # (t_air, samples)
        self.last_tx = -1e9
        self.keyed = False
        self.holdoff_until = 0.0
        self.acc_R = None
        self.acc_T = None
        self.acc_n = 0
        self.frame_pow: list = []
        self.frame_spec: list = []
        self.frame_t0: list = []
        self.misses = 0
        self.last: dict | None = None
        self.nfft_corr = _good_size(2 * self.F)
        self.key_t = 0.0
        self.external: tuple = (None, 0.0, 0.0)

    def set_keyed(self, on: bool, t: float):
        self.keyed = on
        if on:
            self._clear_acc()
            self.misses = 0
            self.key_t = t
        else:
            self.last_tx = t

    # -- an external transmitter ---------------------------------------------
    # The IC-9700 (ohsnb/extrig.py) transmits what we never see: no baseband,
    # so nothing to correlate against. What is left is the downlink itself:
    # what appeared over the baseline while the rig was keyed, around where
    # it was aimed. A carrier (the rig in CW, key down) is one line, and its
    # position is exact to a fraction of a 10 Hz bin. Speech has no line
    # and an unknown spectrum; its edge nearest the suppressed carrier is
    # set by the rig's transmit filter, so it places the signal to a couple
    # of hundred hertz - good enough to see where it went, not to correct
    # it (the radio decides; see Radio._rig_measure).
    EXT_SETTLE = 0.3      # s after the rig's keying is seen before its downlink counts (poll + PA ramp)

    def set_external(self, kind: str | None, lo: float = 0.0, hi: float = 0.0):
        """Measure an external transmitter instead of our own baseband.
        kind "carrier": a single line expected at the channel centre;
        "band": energy expected between lo and hi Hz of the centre (the
        edge nearest 0 is the reference); None: our own transmitter."""
        if (kind, lo, hi) != getattr(self, "external", (None, 0.0, 0.0)):
            self._clear_acc()
        self.external = (kind, float(lo), float(hi))

    def _frame_external(self, frame: np.ndarray, t0: float):
        R = _psd(frame)
        quiet = (not self.keyed) and (t0 > self.last_tx + self.rtt + 0.5)
        if quiet:
            self.baseline = R if self.baseline is None else 0.9 * self.baseline + 0.1 * R
            return None
        if not self.keyed or t0 < self.key_t + self.rtt + self.EXT_SETTLE or t0 < self.holdoff_until:
            return None
        self.acc_R = R if self.acc_R is None else self.acc_R + R
        self.frame_pow.append(R)
        self.acc_n += 1
        if self.acc_n < self.WINDOW:
            return None
        return self._estimate_external()

    def _estimate_external(self):
        kind, lo, hi = self.external
        Ravg = self.acc_R / self.acc_n
        frames = self.frame_pow
        self._clear_acc()
        B = self.baseline if self.baseline is not None else np.full_like(Ravg, float(np.median(Ravg)))
        floor = float(np.median(B)) + 1e-30
        Bf = np.maximum(B, floor * 0.5)
        # Unclipped: the statistics need the noise's spread on both sides of
        # zero (clipped, most bins are exactly 0 and the spread vanishes).
        D = Ravg / Bf - 1.0
        window = self.NARROW if self.trusted else self.WIDE
        mid = self.F // 2
        wl = int(min(window, self.rate * 0.42 - 3000) / self.bin_hz)
        a, b = mid - wl, mid + wl + 1
        Dw = D[a:b]
        med = float(np.median(Dw))
        mad = float(np.median(np.abs(Dw - med))) * 1.4826 + 1e-12
        if kind == "carrier":
            # Three bins: a carrier's Hann main lobe, so a line between two
            # bins scores as high as one on a bin.
            S = np.convolve(Dw, np.ones(3) / 3, mode="same")
            k = int(np.argmax(S))
            z = (S[k] - med) / mad
            kk = _parabolic(Dw, k) if 0 < k < len(Dw) - 1 else float(k)
            err = (a + kk - mid) * self.bin_hz
            sup = slice(max(0, a + k - 3), a + k + 4)
            how = "carrier"
        else:
            # Smooth over ~200 Hz, find the run of bins clearly above the
            # noise nearest the expected edge, and report its edge.
            w = max(3, int(200 / self.bin_hz))
            S = np.convolve(Dw, np.ones(w) / w, mode="same")
            smed = float(np.median(S))
            smad = float(np.median(np.abs(S - smed))) * 1.4826 + 1e-12
            on = S > smed + 6 * smad
            k_peak = int(np.argmax(S))
            z = (S[k_peak] - smed) / smad
            if not on[k_peak]:
                return self._ext_result(0.0, z, 0.0, 0.0, window, "band", confident=False)
            # The contiguous run around the strongest part.
            l = k_peak
            while l > 0 and on[l - 1]:
                l -= 1
            r = k_peak
            while r < len(on) - 1 and on[r + 1]:
                r += 1
            # The smoothing widened the run by half its width each side.
            e_lo = (a + l - mid) * self.bin_hz + w / 2 * self.bin_hz
            e_hi = (a + r - mid) * self.bin_hz - w / 2 * self.bin_hz
            ref_lo = abs(lo) <= abs(hi)
            err = (e_lo - lo) if ref_lo else (e_hi - hi)
            sup = slice(a + l, a + r + 1)
            how = "band"
        own = [float(((Fr - Bf)[sup]).clip(0).sum()) / HANN_ENBW for Fr in frames]
        own_peak = max(own) if own else 0.0
        own_avg = float(np.mean(own)) if own else 0.0
        return self._ext_result(err, z, own_peak, own_avg, window, how,
                                confident=z >= self.CONFIDENT and own_avg > 0)

    def _ext_result(self, err, z, own, own_avg, window, how, confident):
        res = {"err": float(err), "z": float(z), "own": own, "ownAvg": own_avg, "window": window, "how": how,
               "confident": bool(confident)}
        if confident:
            self.misses = 0
        else:
            self.misses += 1
            if self.trusted and self.misses >= 3:
                self.trusted = False
                res["widened"] = True
        self.last = res
        return res

    def retuned(self, t: float):
        """The channel centre moved (VFO change): the baseline belongs to the
        old place."""
        self.baseline = None
        self._clear_acc()
        self.holdoff_until = max(self.holdoff_until, t + self.rtt + 0.3)

    def corrected(self, t: float, latency: float):
        """txCorr changed at stream time t: what comes back before the change
        has done the round trip is from the old frequency."""
        self._clear_acc()
        self.holdoff_until = t + latency + self.rtt + 2 * self.FRAME

    def _clear_acc(self):
        self.acc_R = None
        self.acc_T = None
        self.acc_n = 0
        self.frame_pow = []
        self.frame_spec = []
        self.frame_t0 = []

    def tx(self, bb: np.ndarray, t_air: float):
        self.tx_hist.append((t_air, np.asarray(bb, np.complex64)))
        self.last_tx = t_air + len(bb) / self.tx_rate
        while self.tx_hist and self.tx_hist[0][0] + len(self.tx_hist[0][1]) / self.tx_rate < t_air - 3.0:
            self.tx_hist.popleft()

    def _tx_span(self, t0: float, n: int) -> np.ndarray | None:
        """n TX baseband samples starting at on-air time t0 (zeros where we
        sent nothing), or None if we sent nothing at all in that span."""
        out = np.zeros(n, np.complex64)
        any_ = False
        t1 = t0 + n / self.tx_rate
        # tx() runs on the TX thread and this on the RX thread: iterating
        # the deque itself raised "deque mutated during iteration" whenever
        # a block was sent mid-loop, losing that receive block (and with it
        # a frame of the measurement). tuple() copies it in one step under
        # the GIL.
        for ta, s in tuple(self.tx_hist):
            tb = ta + len(s) / self.tx_rate
            if tb <= t0 or ta >= t1:
                continue
            a = int(round((max(ta, t0) - ta) * self.tx_rate))
            o = int(round((max(ta, t0) - t0) * self.tx_rate))
            m = min(len(s) - a, n - o)
            if m > 0:
                out[o:o + m] = s[a:a + m]
                any_ = True
        return out if any_ else None

    def rx(self, y: np.ndarray, t_end: float):
        self.buf = np.concatenate([self.buf, y])
        self.buf_t0 = t_end - len(self.buf) / self.rate
        results = []
        while len(self.buf) >= self.F:
            frame, self.buf = self.buf[:self.F], self.buf[self.F:]
            t0 = self.buf_t0
            self.buf_t0 += self.F / self.rate
            r = self._frame(frame, t0)
            if r:
                results.append(r)
        return results[-1] if results else None

    def _frame(self, frame: np.ndarray, t0: float):
        if self.external[0] is not None:
            return self._frame_external(frame, t0)
        R = _psd(frame)
        src_t = t0 - self.rtt
        sent = self._tx_span(src_t, self.tF)
        quiet = (sent is None) and (t0 > self.last_tx + self.rtt + 0.5)
        if quiet and not self.keyed:
            self.baseline = R if self.baseline is None else 0.9 * self.baseline + 0.1 * R
            return None
        if sent is None or not self.keyed or t0 < self.holdoff_until:
            return None
        T = self._tx_psd(sent)
        self.acc_R = R if self.acc_R is None else self.acc_R + R
        self.acc_T = T if self.acc_T is None else self.acc_T + T
        self.frame_pow.append(R)
        # 10 ms x 100 Hz spectrogram of the same frame, for finding the delay.
        sub = frame.reshape(10, -1)
        S = np.fft.fftshift(np.abs(np.fft.fft(sub * np.hanning(sub.shape[1]), axis=1)) ** 2, axes=1)
        self.frame_spec.append(S)
        self.frame_t0.append(t0)
        self.acc_n += 1
        if self.acc_n < self.WINDOW:
            return None
        return self._estimate()

    def _tx_psd(self, sent: np.ndarray) -> np.ndarray:
        T = np.zeros(self.F)
        c, h = self.F // 2, self.tF // 2
        T[c - h:c - h + self.tF] = _psd(sent)
        return T

    def _estimate(self):
        Ravg = self.acc_R / self.acc_n
        Tavg = self.acc_T / self.acc_n
        frames, specs, t0s = self.frame_pow, self.frame_spec, self.frame_t0
        self._clear_acc()
        B = self.baseline if self.baseline is not None else np.full_like(Ravg, float(np.median(Ravg)))
        floor = float(np.median(B)) + 1e-30
        Bf = np.maximum(B, floor * 0.5)
        D = np.clip(Ravg / Bf - 1.0, 0.0, 1e6)
        Tn = Tavg / (Tavg.sum() + 1e-30)
        # Stage 1 - averaged spectra. Exact for a carrier or tones; for speech
        # or noise-like audio the averaged shape is smooth and only places
        # the signal to within ~100 Hz. sqrt-weighting so one strong formant
        # does not dominate the match.
        Tw = np.sqrt(Tn)
        n = self.nfft_corr
        C = np.fft.irfft(np.fft.rfft(D, n) * np.conj(np.fft.rfft(Tw, n)), n)
        window = self.NARROW if self.trusted else self.WIDE
        wl = int(min(window, self.rate * 0.42 - 3000) / self.bin_hz)
        lags = np.concatenate([np.arange(0, wl + 1), np.arange(-wl, 0)])
        vals = C[lags % n]
        k = int(np.argmax(vals))
        med = float(np.median(vals))
        mad = float(np.median(np.abs(vals - med))) * 1.4826 + 1e-30
        z = (vals[k] - med) / mad
        lag = int(lags[k])
        ym, y0, yp = C[(lag - 1) % n], C[lag % n], C[(lag + 1) % n]
        dd = ym - 2 * y0 + yp
        frac = 0.0 if dd == 0 else 0.5 * (ym - yp) / dd
        err = (lag + frac) * self.bin_hz
        how = "spectrum"
        # How wide is what we sent? A carrier/tone reference is a few bins;
        # speech is hundreds. Broad references go on to stage 2.
        occ = int((Tn > Tn.max() * 0.01).sum())
        fine = None
        if occ > 30 and D[(np.flatnonzero(Tn > Tn.max() * 0.01) + lag) % self.F].sum() > 0:
            fine = self._fine(frames, specs, t0s, Bf, Tn, lag)
            if fine is not None:
                err, z, how = fine[0], fine[1], "speckle"
        support = np.roll(Tn > Tn.max() * 1e-3, int(round(err / self.bin_hz)))
        own = [float(((Fr - Bf)[support]).clip(0).sum()) / HANN_ENBW for Fr in frames]
        own_peak = max(own) if own else 0.0
        own_avg = float(np.mean(own)) if own else 0.0
        res = {"err": err, "z": z, "own": own_peak, "ownAvg": own_avg, "window": window, "how": how}
        if fine is not None:
            res["delay"] = fine[2]
        if z >= self.CONFIDENT and own_avg > 0 and (occ <= 30 or fine is not None):
            res["confident"] = True
            self.misses = 0
        else:
            res["confident"] = False
            self.misses += 1
            # Nothing found in the narrow window for 3 s: maybe the trusted
            # value is stale (a different SDR, a cold start) - search wide.
            if self.trusted and self.misses >= 3:
                self.trusted = False
                res["widened"] = True
        self.last = res
        return res

    def _fine(self, frames, specs, t0s, Bf, Tn, lag):
        """Stage 2, for broad (speech-like) signals: the fine structure of
        each 100 ms spectrum ("speckle") only matches at the right offset, so
        per-frame correlation - with the time-average removed per bin, which
        takes out both the smooth envelope and any steady carrier - gives a
        peak one bin wide. That needs our transmit history lined up with the
        received frames to a few ms, so first find the delay from the
        envelopes: received power in our band (10 ms steps) against
        transmitted power. Returns (err Hz, z, delay s) or None."""
        # --- delay ---------------------------------------------------------
        sb = specs[0].shape[1]                       # 100 Hz bins in the short spectra
        sbin = self.rate / sb
        idx = np.flatnonzero(Tn > Tn.max() * 0.01)
        f_hz = (idx - self.F // 2) * self.bin_hz + lag * self.bin_hz
        kb = np.unique(np.clip(np.round(f_hz / sbin).astype(int) + sb // 2, 0, sb - 1))
        rxp = np.concatenate([S[:, kb].sum(axis=1) for S in specs])        # 10 ms steps
        rxp = rxp - np.median(rxp)
        t_first = t0s[0]
        step = self.FRAME / 10
        lo_d, hi_d = -0.15, 0.35
        span_t0 = t_first - self.rtt - hi_d
        nsteps = len(rxp) + int(round((hi_d - lo_d) / step)) + 1
        txs = self._tx_span(span_t0, int(round(nsteps * step * self.tx_rate)))
        if txs is None:
            return None
        txp = (np.abs(txs[: nsteps * int(step * self.tx_rate)]) ** 2).reshape(nsteps, -1).mean(axis=1)
        best, best_r = None, 0.3
        a = (rxp - rxp.mean()) / (rxp.std() + 1e-30)
        for j in range(nsteps - len(rxp) + 1):
            b = txp[j:j + len(rxp)]
            r = float(np.mean(a * (b - b.mean()) / (b.std() + 1e-30)))
            if r > best_r:
                best, best_r = j, r
        if best is None:
            return None
        delay = self.rtt + hi_d - best * step       # rx time - delay = tx time
        # --- speckle correlation at that delay -------------------------------
        W = int(400 / self.bin_hz)
        sup = np.flatnonzero(Tn > Tn.max() * 1e-3)
        a0, a1 = sup.min(), sup.max() + 1
        Ts, Ds = [], []
        for Fr, t0 in zip(frames, t0s):
            sent = self._tx_span(t0 - delay, self.tF)
            if sent is None:
                continue
            Ts.append(self._tx_psd(sent)[a0:a1])
            Ds.append(np.clip(Fr / Bf - 1.0, 0, 1e6))
        if len(Ts) < 4:
            return None
        Ts = np.array(Ts)
        Ds = np.array(Ds)
        Ts = Ts - Ts.mean(axis=0)
        lags = np.arange(lag - W, lag + W + 1)
        cols = (np.arange(a0, a1)[None, :] + lags[:, None]) % self.F            # (lags, band)
        Dm = Ds - Ds.mean(axis=0)
        # sum over frames and band of T_j(f) * D_j(f + l)
        C = np.einsum("jb,jlb->l", Ts, Dm[:, cols])
        k = int(np.argmax(C))
        med = float(np.median(C))
        mad = float(np.median(np.abs(C - med))) * 1.4826 + 1e-30
        z = (C[k] - med) / mad
        frac = _parabolic(C, k) - k
        return (lags[k] + frac) * self.bin_hz, z, delay
