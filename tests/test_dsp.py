import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore.dsp import morse
from ohscore.dsp.agc import Agc
from ohscore.dsp.bank import Analysis, Channel, Geometry, Source, Synthesis
from ohscore.dsp.demod import Demod
from ohscore.dsp.fir import OlsFilter, lowpass
from ohscore.dsp.mod import SsbMod
from ohscore.dsp.resample import Resampler
from ohscore.dsp.spectrum import Scope

FS = 1_200_000.0


def tone_power_db(x, f, rate):
    """Power (dB) of the component of x at f, by projection."""
    t = np.arange(len(x)) / rate
    a = np.mean(x * np.exp(-2j * np.pi * f * t))
    return 20 * np.log10(abs(a) + 1e-15)


def run_channel(x, freq, d, block=90_000):
    g = Geometry(FS)
    an, ch = Analysis(g), Channel(g, d, freq)
    out = []
    for i in range(0, len(x), block):
        X, st = an.push(x[i:i + block])
        out.append(ch.take(X, st))
    return np.concatenate(out)


class FilterBank(unittest.TestCase):
    def test_channel_passes_in_band_and_rejects_out_of_band(self):
        n = int(FS)
        t = np.arange(n) / FS
        centre = 150_000.0
        g = Geometry(FS)
        for offset, want in [(0.0, 0.0), (2_000.0, 0.0), (-4_000.0, 0.0), (7_000.0, None), (20_000.0, None)]:
            x = np.exp(2j * np.pi * (centre + offset) * t).astype(np.complex64)
            y = run_channel(x, centre, 100)[200:]
            rate = FS / 100
            if want is not None:
                self.assertAlmostEqual(tone_power_db(y, offset, rate), 0.0, delta=0.1, msg=offset)
            else:
                # Out of band: whatever leaks (anywhere in the channel) is far down.
                self.assertLess(10 * np.log10(np.mean(np.abs(y) ** 2) + 1e-20), -70, msg=offset)
        self.assertIn(300, g.decimations())

    def test_channel_follows_retuning_without_transients(self):
        # Beacon lock nudges the VFO channel every half second. Each frame is
        # mixed consistently, so after a retune the output is immediately the
        # tone at its new offset - no filter ringing - with at most a phase
        # step at the frame edge.
        g = Geometry(FS)
        an, ch = Analysis(g), Channel(g, 100, 100_000.0)
        t = np.arange(int(FS * 2)) / FS
        x = np.exp(2j * np.pi * 101_000.0 * t).astype(np.complex64)
        out, want = [], []
        for i, k in enumerate(range(0, len(x), 90_000)):
            f = 100_000.0 + (37.0 if i % 2 else 0.0)     # crosses a bin boundary
            ch.set_freq(f)
            X, st = an.push(x[k:k + 90_000])
            y = ch.take(X, st)
            out.append(y)
            want.append(np.full(len(y), 101_000.0 - f))
        y = np.concatenate(out)[200:].astype(np.complex128)
        w = np.concatenate(want)[200:]
        inst = np.angle(y[1:] * np.conj(y[:-1])) * 12_000 / (2 * np.pi)
        bad = np.abs(inst - w[1:]) > 0.05
        self.assertLessEqual(bad.sum(), 2 * len(out))   # only the sample straddling each retune

    def test_synthesis_then_analysis_is_transparent(self):
        g = Geometry(FS)
        src, syn = Source(g, 100, freq=-210_123.4), Synthesis(g)
        rate = FS / 100
        n = int(rate * 1.5)
        a = np.exp(2j * np.pi * 750 * np.arange(n) / rate).astype(np.complex64)
        hop = g.L // 100
        wide = np.concatenate([syn.render(1, [(src, a[i:i + hop])]) for i in range(0, n - hop + 1, hop)])
        y = run_channel(wide, -210_123.4, 100)[400:]
        self.assertAlmostEqual(tone_power_db(y, 750.0, rate), 0.0, delta=0.05)


class Modulation(unittest.TestCase):
    def test_ssb_mod_demod_loopback_through_the_bank(self):
        rate = 12_000.0
        n = int(rate * 2)
        t = np.arange(n) / rate
        audio = (0.4 * np.sin(2 * np.pi * 1000 * t) + 0.3 * np.sin(2 * np.pi * 1900 * t)).astype(np.float32)
        mod = SsbMod()
        mod.configure(300, 2700, compressor_db=0.0, voice=False)
        bb = mod(audio)
        # USB: only positive frequencies, so the unwanted sideband is gone.
        self.assertGreater(tone_power_db(bb[2000:], 1000, rate) - tone_power_db(bb[2000:], -1000, rate), 60)
        self.assertLessEqual(np.abs(bb).max(), 1.0 + 1e-6)
        g = Geometry(FS)
        src, syn = Source(g, 100, freq=88_000.0), Synthesis(g)
        hop = g.L // 100
        wide = np.concatenate([syn.render(1, [(src, bb[i:i + hop])]) for i in range(0, n - hop + 1, hop)])
        ch = run_channel(wide, 88_000.0, 100)
        dem = Demod()
        dem.configure("usb", 300, 2700, agc="off")
        out, _ = dem(ch)
        out = out[3000:]
        p1000 = tone_power_db(out.astype(np.complex64), 1000, rate)
        p1900 = tone_power_db(out.astype(np.complex64), 1900, rate)
        # Both tones come back at their audio frequencies with their ratio intact.
        self.assertAlmostEqual(p1000 - p1900, 20 * np.log10(0.4 / 0.3), delta=0.5)
        resid = out - np.real(2 * 10 ** (p1000 / 20) * np.exp(1j * 0))  # sanity: finite
        self.assertTrue(np.isfinite(resid).all())
        # LSB demod of the same channel hears (almost) nothing.
        dem2 = Demod()
        dem2.configure("lsb", -2700, -300, agc="off")
        out2, _ = dem2(ch)
        self.assertLess(np.mean(out2[3000:] ** 2), np.mean(out ** 2) * 1e-5)

    def test_cw_filter_is_narrow(self):
        rate = 12_000.0
        t = np.arange(int(rate)) / rate
        dem = Demod()
        dem.configure("cw", 700 - 125, 700 + 125, agc="off")
        inside, _ = dem(np.exp(2j * np.pi * 700 * t).astype(np.complex64))
        dem2 = Demod()
        dem2.configure("cw", 700 - 125, 700 + 125, agc="off")
        outside, _ = dem2(np.exp(2j * np.pi * 1100 * t).astype(np.complex64))
        self.assertGreater(np.mean(inside[2000:] ** 2) / np.mean(outside[2000:] ** 2 + 1e-20), 1e5)


class GainControl(unittest.TestCase):
    def test_agc_attacks_instantly_and_decays_slowly(self):
        rate = 12_000.0
        agc = Agc(rate, "medium")
        t = np.arange(int(rate * 3)) / rate
        level = np.where((t > 1.0) & (t < 1.5), 1.0, 0.01)
        x = (level * np.sin(2 * np.pi * 800 * t)).astype(np.float32)
        y = np.concatenate([agc(x[i:i + 900]) for i in range(0, len(x), 900)])
        # Settled output level before the burst ~ target (0.3).
        self.assertAlmostEqual(np.abs(y[int(0.8 * rate):int(rate)]).max(), 0.3, delta=0.05)
        # No overshoot when the strong signal arrives.
        self.assertLess(np.abs(y[int(1.0 * rate):int(1.1 * rate)]).max(), 0.35)
        # After the burst: hang, then a slow climb (still quiet 100 ms later).
        self.assertLess(np.abs(y[int(1.55 * rate):int(1.6 * rate)]).max(), 0.05)


class Resampling(unittest.TestCase):
    def test_44k1_and_48k_round_trips(self):
        for rate in (48_000, 44_100):
            up = Resampler(rate, 12_000)
            down = Resampler(12_000, rate)
            t = np.arange(12_000 * 2) / 12_000
            x = np.sin(2 * np.pi * 1234.5 * t).astype(np.float32)
            hi = np.concatenate([up(x[i:i + 700]) for i in range(0, len(x), 700)])
            self.assertAlmostEqual(len(hi) / len(x), rate / 12_000, delta=0.01)
            th = np.arange(len(hi)) / rate
            self.assertAlmostEqual(tone_power_db(hi[5000:].astype(np.complex64) * 2, 1234.5, rate)
                                   - 20 * np.log10(1.0), 0.0, delta=0.3)
            back = down(hi)
            self.assertAlmostEqual(tone_power_db(back[2000:].astype(np.complex64) * 2, 1234.5, 12_000), 0, delta=0.3)
            del th


class Scopes(unittest.TestCase):
    def test_tone_reads_its_level_at_its_bin(self):
        rate = 48_000.0
        sc = Scope(rate, 4800, fps=10, avg=2)
        t = np.arange(int(rate)) / rate
        x = (0.1 * np.exp(2j * np.pi * 5000 * t)).astype(np.complex64)
        lines = sc.process(x)
        self.assertTrue(lines)
        _, db = lines[-1]
        k = int(np.argmax(db))
        self.assertEqual(k - 4800 // 2, 500)
        self.assertAlmostEqual(float(db[k]), -20.0, delta=0.1)


class Misc(unittest.TestCase):
    def test_ols_filter_matches_direct_convolution(self):
        h = lowpass(1000, 12_000, 101)
        x = np.random.default_rng(1).standard_normal(5000).astype(np.complex64)
        f = OlsFilter(h)
        y = np.concatenate([f(x[i:i + 333]) for i in range(0, len(x), 333)])
        ref = np.convolve(x, h)[:len(x)]
        self.assertLess(np.max(np.abs(y - ref)), 1e-4)

    def test_morse_timing(self):
        env = morse.envelope("PARIS", 20, 1000)
        # PARIS is 43 dits without the trailing word gap; dit = 60 ms at 20 wpm.
        self.assertAlmostEqual(len(env) / 1000, 43 * 0.06, delta=0.01)


if __name__ == "__main__":
    unittest.main()
