"""Receive noise reduction (ohscore/dsp/nr.py, WDSP's NR2): what it does to
speech in noise, that it leaves clean audio and strength 0 alone, that
switching it is click-free, what it costs per block, and - in both apps'
engines - that decoders never get its output."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import tempfile
import time
import unittest

import numpy as np

from ohscore.devices.simsignals import voice
from ohscore.dsp import morse
from ohscore.dsp.agc import Agc
from ohscore.dsp.nr import Emnr, NoiseReduction, strength_floor

RATE = 12_000
BLOCK = 900          # the engine's audio block: 75 ms at 12 kHz


def bandlimit(x, lo=300.0, hi=2700.0):
    """Noise as it reaches the demodulator's output: inside the receive
    filter. Noise outside the speech band would be removed by any NR and
    flatter the figures."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))


def pink(rng, n):
    X = np.fft.rfft(rng.standard_normal(n))
    k = np.arange(len(X), dtype=float)
    k[0] = 1.0
    return np.fft.irfft(X / np.sqrt(k), n)


def speech_and_noise(snr_db, kind, seed=3, seconds=8.0):
    """The simulator's voice template (speech-like: glottal pulses through
    moving formants, syllables and pauses) and in-band noise at `snr_db`
    against the speech's power while it is talking."""
    rng = np.random.default_rng(seed)
    s = voice(rng, seconds).real.astype(np.float64)
    n = rng.standard_normal(len(s)) if kind == "white" else pink(rng, len(s))
    n = bandlimit(n)
    talking = np.abs(s) > 0
    n *= np.sqrt(np.mean(s[talking] ** 2) / np.mean(n ** 2)) / 10 ** (snr_db / 20)
    return s, n


def through(proc, x, block=BLOCK):
    m = len(x) // block * block
    return np.concatenate([proc.process(x[i:i + block]) for i in range(0, m, block)])


def segmental_snr(clean, y, frame=240):
    """Mean over 20 ms frames of 10 log10(clean / error), clipped to
    -10..35 dB (the usual limits), over the frames where the speech is
    within 20 dB of its loudest frame: a frame of silence has no SNR."""
    m = len(clean) // frame * frame
    S = clean[:m].reshape(-1, frame)
    E = (y[:m] - clean[:m]).reshape(-1, frame)
    es = (S ** 2).sum(1)
    act = es > 0.01 * es.max()
    v = np.clip(10 * np.log10(es / ((E ** 2).sum(1) + 1e-30) + 1e-30), -10, 35)
    return float(v[act].mean())


def pause_noise_db(clean, x, y, frame=240):
    """How much quieter the output is than the input where nobody is
    talking (frames of the clean speech that are silent)."""
    m = len(clean) // frame * frame
    quiet = np.repeat((clean[:m].reshape(-1, frame) ** 2).sum(1) < 1e-12, frame)
    return float(10 * np.log10(np.mean(y[:m][quiet] ** 2) / np.mean(x[:m][quiet] ** 2)))


def evaluate(snr_db, kind, strength=50.0):
    s, n = speech_and_noise(snr_db, kind)
    x = s + n
    p = Emnr()
    p.floor = strength_floor(strength)
    y = through(p, x)[p.latency:]
    # The first 1.5 s is the noise estimate settling; judged after it.
    a, b = int(1.5 * RATE), len(y)
    s, x, y = s[a:b], x[a:b], y[a:b]
    return segmental_snr(s, x), segmental_snr(s, y), pause_noise_db(s, x, y)


class SpeechInNoise(unittest.TestCase):
    def test_segmental_snr_rises_and_the_pauses_go_quiet(self):
        # Measured on the development machine 05/10/2026 at the default strength (50 %),
        # speech-frame segmental SNR, dB in -> out (gain), and the noise
        # between words:
        #   white  0 dB:  0.1 ->  3.6 (+3.5)  pauses -15.1 dB
        #   white  6 dB:  6.1 ->  7.5 (+1.4)  pauses -14.1 dB
        #   white 12 dB: 12.1 -> 13.1 (+1.0)  pauses -13.2 dB
        #   pink   0 dB:  0.1 ->  3.4 (+3.2)  pauses -15.0 dB
        #   pink   6 dB:  6.1 ->  7.2 (+1.1)  pauses -14.2 dB
        #   pink  12 dB: 12.1 -> 12.9 (+0.8)  pauses -13.1 dB
        # An MMSE gain buys most where the noise is worst; at 12 dB it
        # mostly removes the hiss between words, which is what the ear
        # notices. The limits leave margin under those figures but would
        # catch an estimator that stopped tracking (pauses near 0 dB) or a
        # gain that ate speech (segmental SNR falling).
        need = {0: 2.0, 6: 0.6, 12: 0.3}
        for kind in ("white", "pink"):
            for snr in (0, 6, 12):
                before, after, pauses = evaluate(snr, kind)
                print(f"\nNR {kind} {snr:2d} dB: segmental SNR {before:.1f} -> {after:.1f} dB "
                      f"({after - before:+.1f}), pauses {pauses:.1f} dB", end="")
                self.assertGreater(after - before, need[snr], (kind, snr))
                self.assertLess(pauses, -10.0, (kind, snr))

    def test_more_strength_takes_more_noise_out(self):
        got = [evaluate(6, "white", st)[2] for st in (20, 50, 100)]
        self.assertLess(got[1], got[0] - 2)
        self.assertLess(got[2], got[1] - 2)


class CleanAudio(unittest.TestCase):
    def test_clean_cw_comes_through_unchanged(self):
        # A keyed 700 Hz CW signal 40 dB over in-band noise, NR at full
        # strength: while the key is down the note is within 0.5 dB of its
        # level, and the waveform's error is at least 25 dB down on it once
        # the estimate has settled. (Keyed, as CW is: a carrier held
        # steady for longer than the estimator's 1.5 s minimum window is
        # indistinguishable from a noise floor and is reduced like one - a
        # property of minimum statistics, WDSP's included.)
        rng = np.random.default_rng(4)
        env = morse.envelope("CQ CQ DE G4XYZ G4XYZ K", 20.0, RATE, tail=0.3)
        env = np.tile(env, int(np.ceil(8 * RATE / len(env))))[:8 * RATE]
        t = np.arange(len(env)) / RATE
        cw = 0.3 * env * np.sin(2 * np.pi * 700 * t)
        n = bandlimit(rng.standard_normal(len(t)))
        n *= np.sqrt(np.mean(cw[env > 0.99] ** 2) / np.mean(n ** 2)) / 100
        p = Emnr()
        p.floor = strength_floor(100)
        y = through(p, cw + n)[p.latency:]
        a = 2 * RATE
        ref, out, down = cw[a:len(y)], y[a:], env[a:len(y)] > 0.99
        level = 10 * np.log10(np.mean(out[down] ** 2) / np.mean(ref[down] ** 2))
        err = 10 * np.log10(np.mean((out[down] - ref[down]) ** 2) / np.mean(ref[down] ** 2))
        print(f"\nNR clean CW: level {level:+.2f} dB, error {err:.1f} dB", end="")
        self.assertLess(abs(level), 0.5)
        self.assertLess(err, -25)

    def test_clean_speech_comes_through_close_to_the_input(self):
        # Speech 40 dB over the noise: segmental SNR of the output against
        # the clean speech stays above 20 dB, i.e. what NR changes in a
        # strong signal is at least 20 dB down on it, frame by frame.
        s, n = speech_and_noise(40, "white", seed=8)
        p = Emnr()
        p.floor = strength_floor(100)
        y = through(p, s + n)[p.latency:]
        a = int(1.5 * RATE)
        self.assertGreater(segmental_snr(s[a:len(y)], y[a:]), 20.0)

    def test_strength_zero_is_transparent(self):
        rng = np.random.default_rng(5)
        x = rng.standard_normal(3 * RATE)
        p = Emnr()
        p.floor = strength_floor(0)
        y = through(p, x)
        L = p.latency
        np.testing.assert_allclose(y[L:], x[:len(y) - L], atol=1e-12)

    def test_off_is_an_exact_bypass(self):
        nr = NoiseReduction()
        nr.configure(False, 100.0, "usb")
        x = np.random.default_rng(6).standard_normal(BLOCK).astype(np.float32)
        self.assertIs(nr(x, 1.0), x)
        # And in a mode it does not apply to, whatever the switch says.
        nr.configure(True, 100.0, "ft8")
        self.assertIs(nr(x, 1.0), x)


class Switching(unittest.TestCase):
    def test_toggling_makes_no_click(self):
        # A steady tone, NR switched on and off twice. A click is a step in
        # the waveform; its signature is a second difference far above the
        # tone's own (A * (2 pi f / fs)^2). The fades are a blend of the
        # tone with itself 45 ms later, so the largest second difference
        # anywhere in the output must stay at the input's.
        t = np.arange(8 * RATE) / RATE
        x = (0.3 * np.sin(2 * np.pi * 600 * t)).astype(np.float32)
        nr = NoiseReduction()
        nr.configure(False, 100.0, "usb")
        out = []
        for i in range(0, len(x), BLOCK):
            sec = i / RATE
            nr.configure(1.0 <= sec < 3.0 or 4.0 <= sec < 6.0, 100.0, "usb")
            out.append(nr(x[i:i + BLOCK], 2.0))
        y = np.concatenate(out).astype(np.float64)
        d2_in = np.abs(np.diff(x.astype(np.float64), 2)).max()
        d2_out = np.abs(np.diff(y, 2)).max()
        self.assertLess(d2_out, 1.05 * d2_in)
        self.assertIsNone(nr.proc)             # off and faded out: nothing left running

    def test_a_mode_change_fades_like_a_switch(self):
        t = np.arange(4 * RATE) / RATE
        x = (0.3 * np.sin(2 * np.pi * 900 * t)).astype(np.float32)
        nr = NoiseReduction()
        out = []
        for i in range(0, len(x), BLOCK):
            nr.configure(True, 100.0, "usb" if i < 2 * RATE else "psk31")
            out.append(nr(x[i:i + BLOCK]))
        y = np.concatenate(out).astype(np.float64)
        self.assertLess(np.abs(np.diff(y, 2)).max(), 1.05 * np.abs(np.diff(x.astype(np.float64), 2)).max())
        np.testing.assert_array_equal(y[-BLOCK:], x[-BLOCK:])   # bypassed, exactly, once faded

    def test_works_on_the_audio_before_the_agc(self):
        # Speech at 12 dB SNR with a long pause, through the receiver's
        # AGC. Given the AGC's gain, NR takes the pause's noise well down;
        # without it, the AGC lifts the noise ~20 dB in the pause, the
        # minimum-statistics estimate stays at the level under the words,
        # and the pause - where NR is wanted most - comes through nearly
        # as it was (measured: -15.5 dB with the gain, -0.8 dB without).
        rng = np.random.default_rng(5)
        s = voice(rng, 10.0).real.astype(np.float64)
        s[4 * RATE:6 * RATE] = 0
        n = bandlimit(rng.standard_normal(len(s)))
        n *= np.sqrt(np.mean(s[np.abs(s) > 0] ** 2) / np.mean(n ** 2)) / 10 ** (12 / 20)
        x = ((s + n) * 1e-3).astype(np.float32)
        res = {}
        for with_gain in (True, False):
            agc, nr = Agc(RATE, "medium"), NoiseReduction()
            nr.configure(True, 50.0, "usb")
            heard, agcd = [], []
            for i in range(0, len(x) // BLOCK * BLOCK, BLOCK):
                a = agc(x[i:i + BLOCK])
                agcd.append(a)
                heard.append(nr(a, agc.gain if with_gain else None))
            y = np.concatenate(heard).astype(np.float64)
            a = np.concatenate(agcd).astype(np.float64)
            L = nr.proc.latency
            y, a = y[L:], a[:len(y) - L]
            p0, p1 = int(4.3 * RATE), int(5.9 * RATE)
            res[with_gain] = 10 * np.log10(np.mean(y[p0:p1] ** 2) / np.mean(a[p0:p1] ** 2))
        self.assertLess(res[True], -10.0)
        self.assertLess(res[True], res[False] - 6.0)


class Cost(unittest.TestCase):
    def test_time_per_block(self):
        # Recorded in docs/PERF.md: 1.1 ms per 75 ms block on the development machine (Ryzen 9
        # 6900HX), ~1.5 % of one core. The limit is ten times that - only a
        # gross regression (a per-sample loop, a Bluestein-length FFT)
        # fails, not a busy machine.
        rng = np.random.default_rng(9)
        x = rng.standard_normal(20 * BLOCK).astype(np.float32)
        nr = NoiseReduction(warmup=0.0)
        nr.configure(True, 50.0, "usb")
        for i in range(0, 4 * BLOCK, BLOCK):          # numpy's FFT plans, and the fade
            nr(x[i:i + BLOCK], 1.0)
        times = []
        for i in range(4 * BLOCK, len(x), BLOCK):
            t0 = time.perf_counter()
            nr(x[i:i + BLOCK], 1.0)
            times.append(time.perf_counter() - t0)
        ms = 1e3 * float(np.median(times))
        print(f"\nNR: {ms:.2f} ms per 75 ms block ({ms / 75 * 100:.1f} % of one core)", end="")
        self.assertLess(ms, 11.0)


class InTheEngine(unittest.TestCase):
    """Each app's receive chain: whatever NR does to the speaker's audio,
    the decoder queue gets exactly what the demodulator produced."""

    def _spy(self, r):
        seq = []
        demod = r._demodulate

        def demodulate(*a, **kw):
            audio, level = demod(*a, **kw)
            seq.append(("d", r.st["mode"], audio.copy()))
            return audio, level
        r._demodulate = demodulate
        play = r.audio.play

        def played(a):
            seq.append(("p", None, np.array(a, copy=True)))
            return play(a)
        r.audio.play = played
        put = r.decode_q.put_nowait

        def queued(item):
            if item is not None:                       # None: stop() waking the decode thread
                seq.append(("q", None, np.array(item[0], copy=True)))
            return put(item)
        r.decode_q.put_nowait = queued
        return seq

    def _check(self, seq, nr_mode):
        decoded = nr_changed = 0
        last = None
        for kind, mode, a in seq:
            if kind == "d":
                last = (mode, a)
            elif kind == "q" and last is not None:
                np.testing.assert_array_equal(a, last[1])
                decoded += 1
            elif kind == "p" and last is not None and last[0] == nr_mode and len(a) == len(last[1]):
                # Volume 0.5: NR is in the speaker's path if what was
                # played is not simply the demodulated audio, halved.
                if not np.allclose(a, 0.5 * last[1], atol=1e-6):
                    nr_changed += 1
        return decoded, nr_changed

    def _run(self, r, pump, modes, nr_mode):
        r.start()
        seq = self._spy(r)
        agc = r.demod.agc
        for m in modes:
            r.set(mode=m)
            pump(r, m)
        # Switching NR never replaces or resets the receiver's AGC.
        r.set(nr=False)
        pump(r, nr_mode)
        self.assertIs(r.demod.agc, agc)
        decoded, nr_changed = self._check(list(seq), nr_mode)
        self.assertGreater(decoded, 20)
        self.assertGreater(nr_changed, 5)

    def test_nb_decoders_get_the_audio_before_nr(self):
        from helpers import make_radio, run_sim
        tmp = tempfile.mkdtemp()
        r = make_radio(tmp, nr=True, nrStrength=100.0, volume=0.5, mode="usb", simSignals=True)
        try:
            # CW has both a decoder and NR - the case that matters; the
            # digital modes' decoders are checked the same way.
            self._run(r, lambda radio, _m: run_sim(radio, 1.5), ["cw", "rtty", "psk31", "ft8", "sstv", "usb"],
                      "usb")
        finally:
            r.stop()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ham_decoders_get_the_audio_before_nr(self):
        from ham_helpers import close, make_radio

        def pump(radio, _m):
            n0 = radio.rx_samples
            end = time.monotonic() + 30
            while radio.rx_samples - n0 < 1.5 * radio.geo.fs and time.monotonic() < end:
                radio.heartbeat()
                time.sleep(0.02)
        r = make_radio(nr=True, nrStrength=100.0, volume=0.5, mode="usb")
        try:
            self._run(r, pump, ["cw", "rtty", "psk31", "fm", "usb"], "usb")
        finally:
            close(r)


if __name__ == "__main__":
    unittest.main()
