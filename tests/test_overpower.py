"""ohsnb.dsp.overpower: over-power signals and LEILA's siren, as the live
watch and the analyser both judge them.

The siren cases run on the real thing: tests/data/leila-sirens.npz holds
4 kS/s excerpts of Brian's two receive recordings of 17/10/2026
(openhamshack-nb-20261017-154145Z and -154414Z, during the 7P8GE FT8 pile-up),
three sirens and two stretches with none - the pile-up itself and an SSB
station over the beacon. Each excerpt is put back at 48 kS/s, with noise
at its own floor, so it goes through the same filter bank geometry
(50 Hz bins, 15 ms hops) the radio uses at 1.2 MS/s."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import time
import unittest
from pathlib import Path

import numpy as np

from ohscore.dsp.bank import Analysis, Geometry
from ohsnb import bandplan
from ohsnb.dsp import overpower

DATA = Path(__file__).parent / "data" / "leila-sirens.npz"
UP = 48_000.0


def _excerpt(name: str) -> tuple[np.ndarray, dict]:
    with np.load(DATA) as z:
        iq = z[name].astype(np.float32)
        info = json.loads(str(z[name + "_info"]))
    x = (iq[:, 0] + 1j * iq[:, 1]) / 32768.0
    # Up to UP by zero-padding the spectrum: the excerpt sits in the middle
    # of a wider stream, as it did in the recording.
    n = len(x)
    m = int(n * UP / info["rate"])
    X = np.fft.fft(x)
    Y = np.zeros(m, complex)
    h = n // 2
    Y[:h], Y[-(n - h):] = X[:h], X[h:]
    y = np.fft.ifft(Y) * (m / n)
    # Noise at the excerpt's own floor outside its 4 kHz, so the siren is
    # judged against a floor, not against nothing.
    floor = np.percentile(np.abs(X) ** 2, 20) / n / info["rate"]
    rng = np.random.default_rng(1)
    y = y + np.sqrt(floor * UP / 2) * (rng.standard_normal(m) + 1j * rng.standard_normal(m))
    return y.astype(np.complex64), info


def _sirens(name: str) -> list[dict]:
    y, info = _excerpt(name)
    geo = Geometry(UP)
    an = Analysis(geo)
    fc = info["centre_hz"]
    s = overpower.Siren(geo, span=(fc - 6_000.0, fc + 6_000.0))
    step = 5 * geo.L
    for i in range(0, len(y), step):
        X, starts = an.push(y[i:i + step])
        s.push(X, starts, fc)
    return [e for e in s.sirens if e["looks"] >= overpower.SIREN_MIN_LOOKS]


class RealSirens(unittest.TestCase):
    """Where each siren was measured by hand (docs/qo100-research.md
    section 9): its two tones, from the recordings' own IQ."""

    def _one(self, name, lo, hi):
        found = _sirens(name)
        self.assertEqual(len(found), 1, found)
        e = found[0]
        self.assertAlmostEqual(e["lo"], lo, delta=25.0)
        self.assertAlmostEqual(e["hi"], hi, delta=25.0)
        return e

    def test_the_first_siren_of_154145(self):
        e = self._one("siren_154145_a", 10_489_540_016.0, 10_489_540_229.0)
        self.assertGreater(e["t_last"] - e["t_start"], 2.5)      # 5 s of siren in the excerpt

    def test_the_second_siren_of_154145_beside_a_stronger_ft8_station(self):
        self._one("siren_154145_b", 10_489_541_298.0, 10_489_541_504.0)

    def test_the_siren_of_154414_that_starts_under_the_pileup(self):
        self._one("siren_154414", 10_489_540_444.0, 10_489_540_650.0)

    def test_the_pileup_itself_is_no_siren(self):
        self.assertEqual(_sirens("ft8_pileup"), [])

    def test_an_ssb_voice_over_the_beacon_is_no_siren(self):
        self.assertEqual(_sirens("ssb_voice"), [])


# --------------------------------------------------------------- synthetic
FS = 1_200_000.0
DC = (bandplan.DL_LO + bandplan.DL_HI) / 2.0
MID = bandplan.BEACONS["middle"]["ref"]
BEACON_A = 0.05


def _stream(seconds: float, extra, seed: int = 3):
    """Blocks of a 1.2 MS/s stream centred on the transponder: noise, the
    middle beacon (400 bd BPSK, amplitude BEACON_A) and `extra(t)` (complex
    baseband, DC-relative), generated a block at a time so a test never
    holds the whole stream."""
    rng = np.random.default_rng(seed)
    geo = Geometry(FS)
    step = 5 * geo.L
    n = int(seconds * FS)
    syms = rng.choice([-1.0, 1.0], size=int(seconds * 400) + 2)
    for i in range(0, n, step):
        t = (i + np.arange(min(step, n - i))) / FS
        b = BEACON_A * syms[(t * 400).astype(int)] * np.exp(2j * np.pi * (MID - DC) * t)
        noise = 0.002 * (rng.standard_normal(len(t)) + 1j * rng.standard_normal(len(t)))
        yield (b + noise + extra(t)).astype(np.complex64)


def _run(seconds, extra, seed=3):
    geo = Geometry(FS)
    an = Analysis(geo)
    d = overpower.Detector(geo)
    cpu = 0.0
    for x in _stream(seconds, extra, seed):
        X, starts = an.push(x)
        c0 = time.thread_time()
        d.lines(x, DC, True)
        d.spectra(X, starts, DC)
        cpu += time.thread_time() - c0
    return d, cpu


def _carrier(f_abs, db_vs_beacon, on=None):
    a = BEACON_A * 10 ** (db_vs_beacon / 20.0)

    def sig(t):
        s = a * np.exp(2j * np.pi * (f_abs - DC) * t)
        return s if on is None else s * on(t)
    return sig


HOT = bandplan.DL_LO + 300_000.0       # well clear of every beacon's guard zone


class OverPower(unittest.TestCase):
    def test_a_station_5_db_over_the_beacon_is_an_event_where_it_is(self):
        d, _ = _run(8.0, _carrier(HOT, 5.0))
        ops = [e for e in d.events() if e["kind"] == "overpower"]
        self.assertEqual(len(ops), 1, ops)
        e = ops[0]
        self.assertAlmostEqual(e["freq"], HOT, delta=100.0)
        self.assertAlmostEqual(e["excessDb"], 5.0, delta=1.5)
        self.assertTrue(e["active"])
        self.assertFalse(e["leila"])           # a steady carrier: no siren

    def test_a_station_under_the_beacon_is_not(self):
        d, _ = _run(8.0, _carrier(HOT, -3.0))
        self.assertEqual(d.events(), [])

    def test_ft8_signals_below_the_beacon_are_nothing(self):
        # Four FT8 stations 6 dB under the beacon, 300 Hz apart, 8-FSK at
        # 6.25 baud, on for 12.6 s of each 15.
        rng = np.random.default_rng(5)
        tones = rng.integers(0, 8, size=(4, 200))

        def ft8(t):
            out = np.zeros(len(t), complex)
            for k in range(4):
                f = HOT + 300.0 * k + 6.25 * tones[k][(t / 0.16).astype(int) % 200]
                on = (t % 15.0) < 12.6
                out += BEACON_A * 10 ** (-6 / 20) * on * np.exp(2j * np.pi * (f - DC) * t)
            return out
        d, _ = _run(8.0, ft8)
        self.assertEqual(d.events(), [])

    def test_a_beacon_too_weak_to_compare_with_judges_nothing(self):
        geo = Geometry(FS)
        d = overpower.Detector(geo)
        rng = np.random.default_rng(9)
        for _ in range(int(4 * FS / (5 * geo.L))):
            x = (0.002 * (rng.standard_normal(5 * geo.L) + 1j * rng.standard_normal(5 * geo.L))).astype(np.complex64)
            d.lines(x, DC, True)
        self.assertEqual(d.beacon, "weak")
        self.assertEqual(d.events(), [])


def _siren(f_lo_abs, db_vs_beacon=2.0, spacing=205.0, t0=1.0, t1=6.0):
    a = BEACON_A * 10 ** (db_vs_beacon / 20.0)

    def sig(t):
        on = (t >= t0) & (t < t1)
        # Continuous phase across the switches, as a real oscillator.
        ph = 2 * np.pi * ((f_lo_abs - DC) * t + spacing * _upper_time(t, t0))
        return a * on * np.exp(1j * ph)
    return sig


def _upper_time(t, t0):
    """Seconds spent on the upper tone since t0, at each t (for phase)."""
    rel = np.maximum(t - t0, 0.0)
    whole, part = np.floor(rel / 0.4), rel % 0.4
    return whole * 0.2 + np.maximum(part - 0.2, 0.0)


class Leila(unittest.TestCase):
    def test_a_siren_over_a_station_marks_it(self):
        both = lambda t: _carrier(HOT + 100.0, 6.0)(t) * (t < 4.0) + _siren(HOT, t0=4.5, t1=9.5)(t)  # noqa: E731
        d, _ = _run(11.0, both)
        ev = d.events()
        sirens = [e for e in ev if e["kind"] == "leila"]
        self.assertEqual(len(sirens), 1, ev)
        s = sirens[0]
        self.assertAlmostEqual(s["lo"], HOT, delta=25.0)
        self.assertAlmostEqual(s["hi"], HOT + 205.0, delta=25.0)
        op = [e for e in ev if e["kind"] == "overpower"]
        self.assertTrue(op and op[0]["leila"] and op[0]["siren"] == s["id"])
        self.assertEqual(s["on"], op[0]["id"])

    def test_a_tone_swept_back_and_forth_is_not_the_siren(self):
        # What the analyser guessed LEILA was before the recordings: a
        # warble sweeping +-300 Hz at 0.5 Hz.
        def swept(t):
            ph = 2 * np.pi * (HOT - DC) * t + (300.0 / 0.5) * np.sin(2 * np.pi * 0.5 * t)
            return BEACON_A * 2 * np.exp(1j * ph)
        d, _ = _run(8.0, swept)
        self.assertEqual([e for e in d.events() if e["kind"] == "leila"], [])


def _three_beacons(dc: float, seconds: float, extra=None, seed: int = 11):
    """Blocks of a 1.2 MS/s stream with DC at `dc` (a true downlink: rxCorr
    0) and all three beacons at the same power, BEACON_A**2 - the lower and
    upper as F1A (two tones 400 Hz apart, keyed at random every 100 ms,
    the power constant), the middle as 400 bd BPSK - plus `extra(t, dc)`."""
    rng = np.random.default_rng(seed)
    geo = Geometry(FS)
    step = 5 * geo.L
    n = int(seconds * FS)
    syms = rng.choice([-1.0, 1.0], size=int(seconds * 400) + 2)
    keys = rng.integers(0, 2, size=(2, int(seconds * 10) + 2))
    low, up = bandplan.BEACONS["lower"]["dl"], bandplan.BEACONS["upper"]["dl"]
    for i in range(0, n, step):
        t = (i + np.arange(min(step, n - i))) / FS
        b = BEACON_A * syms[(t * 400).astype(int)] * np.exp(2j * np.pi * (MID - dc) * t)
        # Lower: space 10489.5000, mark .5004; upper: mark .9996, space 10490.0000.
        f_lo = low + 400.0 * keys[0][(t * 10).astype(int)]
        f_up = up - 400.0 * keys[1][(t * 10).astype(int)]
        b = b + BEACON_A * (np.exp(2j * np.pi * (f_lo - dc) * t) + np.exp(2j * np.pi * (f_up - dc) * t))
        noise = 0.002 * (rng.standard_normal(len(t)) + 1j * rng.standard_normal(len(t)))
        yield (b + noise + (extra(t, dc) if extra else 0.0)).astype(np.complex64)


class BeaconsWhereNbTunes(unittest.TestCase):
    """NB puts the receiver's DC 3.5 kHz below the middle beacon
    (ohsnb.radio.RX_CENTRE_DL) and re-centres once rxCorr has moved 1.5 kHz,
    so the beacon sits 2-5 kHz from DC. On 17/10/2026 the middle beacon was
    suspected of reading 5-6 dB low there, because BATC's NB WebSDR showed
    it 6.5-7 dB over the CW beacons while NB's recordings showed all three
    within ~1 dB. It is not: the recordings' noise floor (which every stage
    after the LNB shapes exactly as it shapes a signal) is flat to 0.1 dB
    from DC out past 100 kHz, and the WebSDR's own noise floor has the same
    ~5.5 dB hump towards the transponder's middle as its beacons do - each
    beacon over its local noise agrees with NB's to within 0.6 dB
    (docs/qo100-research.md section 9). These keep NB's own DSP honest at
    that placement: equal beacons read equal, and a station level with
    the beacon is not "over" it."""

    def _levels(self, dc_below_mid: float) -> dict:
        from ohsnb.radio import RX_CENTRE_DL
        dc = MID - dc_below_mid
        self.assertLess(abs(dc - RX_CENTRE_DL), 1_501.0)      # where NB really puts it, re-centre slack included
        d = overpower.Detector(Geometry(FS))
        got = {"lower": [], "upper": []}
        for x in _three_beacons(dc, 2.5):
            for _end, db in d.scope.process(x):
                # No guards and a margin under zero: each other beacon comes
                # back as a "hit" whose excess is its level over the middle's.
                state, hits = overpower.judge_line(dc + d.offsets, db, d.scope.bin_hz, margin_db=-1.5, guards=[])
                self.assertEqual(state, "ok")
                for name in got:
                    f = bandplan.BEACONS[name]["ref"]
                    got[name] += [exc for lo, hi, exc in hits if lo - 600.0 <= f <= hi + 600.0]
        self.assertTrue(got["lower"] and got["upper"], got)
        return got

    def test_equal_beacons_read_equal_with_dc_where_nb_tunes(self):
        for below in (3_500.0, 2_000.0, 5_000.0):
            for name, excess in self._levels(below).items():
                for e in excess:
                    self.assertAlmostEqual(e, 0.0, delta=1.0, msg=f"{name}, DC {below:g} Hz below the beacon")

    def test_an_ft8_station_level_with_the_beacon_is_not_over_it(self):
        from ohsnb.radio import RX_CENTRE_DL
        rng = np.random.default_rng(6)
        tones = rng.integers(0, 8, size=200)
        f0 = bandplan.DL_LO + 41_000.0

        def ft8(t, dc):
            f = f0 + 6.25 * tones[(t / 0.16).astype(int) % 200]
            return BEACON_A * np.exp(2j * np.pi * (f - dc) * t)
        geo = Geometry(FS)
        an = Analysis(geo)
        d = overpower.Detector(geo)
        for x in _three_beacons(RX_CENTRE_DL, 6.0, ft8):
            X, starts = an.push(x)
            d.lines(x, RX_CENTRE_DL, True)
            d.spectra(X, starts, RX_CENTRE_DL)
        self.assertEqual(d.beacon, "ok")
        self.assertEqual(d.events(), [])


class Cost(unittest.TestCase):
    def test_the_watch_costs_a_small_share_of_a_core(self):
        # ~4.5 % of one core on the development VM, measured over the real
        # recordings; the bound is generous so a slow test host cannot fail
        # it, but a regression that multiplies the cost will.
        seconds = 6.0
        _d, cpu = _run(seconds, _carrier(HOT, 5.0))
        self.assertLess(cpu / seconds, 0.30)


if __name__ == "__main__":
    unittest.main()
