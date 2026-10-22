"""Auto-tune listening until it is sure (ohscore/dsp/autotune.py Listener,
listen): its first look is auto_tune's answer on the same seconds, it
answers as soon as it is sure, more listening turns refusals into right
answers without ever turning one into a wrong answer, and what more
listening cannot change it refuses at once."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore.devices import simsignals as sg
from ohscore.dsp import autotune as at

RATE = 12_000.0
FIRST = int(at.CAPTURE_SECONDS * RATE)


def station(seed, carrier, snr_db, sideband="usb", seconds=at.LISTEN_SECONDS, talk=(0.0, 1.0)):
    """The simulator's voice with its carrier `carrier` Hz from the dial, in
    white noise `snr_db` under the voice's power (in 2.4 kHz, measured over
    the talking part)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    z = sg.voice(rng, seconds + 1.0, talk=talk)[:n].astype(np.complex128)
    if sideband == "lsb":
        z = np.conj(z)
    x = z * np.exp(2j * np.pi * carrier * np.arange(n) / RATE)
    ps = np.mean(np.abs(z[np.abs(z) > 0]) ** 2)
    w = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    return (x + w * np.sqrt(ps / 10 ** (snr_db / 10) * RATE / 2400 / 2)).astype(np.complex64)


class FirstLook(unittest.TestCase):
    def test_the_first_look_is_auto_tune_on_the_same_seconds(self):
        for seed, sb, carrier in ((1, "usb", 45.0), (2, "lsb", -60.0), (3, "usb", 220.0)):
            with self.subTest(seed=seed):
                x = station(seed, carrier, 10.0, sb)
                a = at.auto_tune(x[:FIRST], sb)
                b = at.Listener(sb).look(x[:FIRST])
                if a.ok:
                    self.assertTrue(b is not None and b.ok)
                    self.assertAlmostEqual(a.offset, b.offset, places=6)
                else:
                    # Unsure at the first look means listen on, not refuse...
                    # unless it is not a voice at all.
                    self.assertTrue(b is None or b.why == a.why, (a.why, b))

    def test_the_first_look_is_auto_tune_when_it_comes_a_block_late(self):
        # The engine looks once it has collected at least 4 s, in whole
        # receive blocks, so its first look holds a little more than 4 s
        # (4.05 s was typical). It is still the first look: it answers
        # wherever auto_tune() on those same samples would.
        late = FIRST + 600
        answered = 0
        for seed, sb, carrier in ((1, "usb", 45.0), (2, "lsb", -60.0), (3, "usb", 220.0), (4, "usb", -130.0)):
            with self.subTest(seed=seed):
                x = station(seed, carrier, 10.0, sb)
                a = at.auto_tune(x[:late], sb)
                lis = at.Listener(sb)
                self.assertTrue(lis.due(late))
                b = lis.look(x[:late])
                if a.ok:
                    answered += 1
                    self.assertTrue(b is not None and b.ok, b and b.why)
                    self.assertAlmostEqual(a.offset, b.offset, places=6)
        self.assertGreater(answered, 0)

    def test_a_clear_voice_is_answered_at_the_first_look(self):
        r = at.listen(station(1000 + 37, 45.0, 20.0), "usb")
        self.assertTrue(r.ok, r.why)
        self.assertEqual(r.details["heard"], at.CAPTURE_SECONDS)
        self.assertLess(abs(r.offset - 45.0), 10.0)


class ListensLonger(unittest.TestCase):
    """At 3 dB, where four seconds often leave it unsure: past the first
    look it answers only when the voice's harmonics and its leaked carrier
    agree, so a voice that leaks is answered more often by listening on,
    one that does not is answered no more often, and neither is ever
    answered wrong."""

    def leak(self, x, carrier):
        """The station's carrier, leaking 25 dB under its voice."""
        return x + 10 ** (-25 / 20) * np.sqrt(np.mean(np.abs(x) ** 2)) * np.exp(
            2j * np.pi * carrier * np.arange(len(x)) / RATE)

    def test_more_answers_none_wrong(self):
        counts = {False: [0, 0], True: [0, 0]}
        for k in range(16):
            carrier = (-180.0, -60.0, 45.0, 220.0)[k % 4]
            sb = "usb" if k % 2 else "lsb"
            plain = station(500 + k, carrier, 3.0, sb)
            for leaking, x in ((False, plain), (True, self.leak(plain, carrier))):
                a = at.auto_tune(x[:FIRST], sb)
                b = at.listen(x, sb)
                for r in (a, b):
                    if r.ok:
                        self.assertLess(abs(r.offset - carrier), 10.0, f"{sb} {carrier:+.0f} Hz: {r}")
                if b.ok:
                    self.assertLessEqual(b.details["heard"], at.LISTEN_SECONDS)
                    if b.details["heard"] > at.CAPTURE_SECONDS:
                        self.assertEqual(b.details.get("how"), "line")
                counts[leaking][0] += a.ok
                counts[leaking][1] += b.ok
        self.assertEqual(counts[False][1], counts[False][0])
        self.assertGreater(counts[True][1], counts[True][0])

    def test_a_voice_that_starts_late_is_waited_for(self):
        # Breath and a syllable or two in the first look, the over after.
        x = station(77, -60.0, 10.0, talk=(0.25, 1.0), seconds=at.LISTEN_SECONDS)
        r = at.listen(x, "usb")
        if r.ok:
            self.assertLess(abs(r.offset + 60.0), 10.0)
            self.assertGreater(r.details["heard"], at.CAPTURE_SECONDS)


class RefusesAtOnce(unittest.TestCase):
    """Nothing there, or not a voice: more listening cannot change that,
    so it says so after the first look, not at the end."""

    def check(self, x, words):
        lis = at.Listener("usb")
        r = lis.look(x[:FIRST])
        self.assertIsNotNone(r)
        self.assertFalse(r.ok)
        self.assertIn(words, r.why)

    def test_an_empty_band(self):
        rng = np.random.default_rng(1)
        n = int(at.LISTEN_SECONDS * RATE)
        self.check((rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 1e-2, "nothing near the dial")

    def test_a_carrier(self):
        rng = np.random.default_rng(2)
        n = int(at.LISTEN_SECONDS * RATE)
        t = np.arange(n) / RATE
        x = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 1e-2 + 0.2 * np.exp(2j * np.pi * 700 * t)
        self.check(x, "carrier")


class NeverSure(unittest.TestCase):
    def test_two_stations_taking_turns_a_pitch_apart_are_not_averaged(self):
        # A QSO on one frequency, the partner 70 Hz off: a long listen hears
        # both. It may land either (each is a station the operator can
        # hear), or refuse; it must not land between them.
        # The first speaks for the first three seconds, the partner after.
        for k in range(8):
            a = station(11 + 2 * k, -60.0, 12.0, talk=(0.0, 0.25))
            b = station(12 + 2 * k, 10.0, 12.0, talk=(0.25, 1.0))
            r = at.listen(a + b, "usb")
            if r.ok:
                self.assertLess(min(abs(r.offset + 60.0), abs(r.offset - 10.0)), 10.0, r)

    def test_unsure_to_the_end_it_refuses_with_the_last_reason(self):
        lis = at.Listener("usb", most=6.0)
        rng = np.random.default_rng(9)
        # Evenly spaced tones that wander in level like speech: past the
        # spectrum's checks, never a voice's pitch.
        n = int(6.0 * RATE)
        t = np.arange(n) / RATE
        env = np.repeat(rng.uniform(0.1, 1.0, n // 1200 + 1), 1200)[:n]
        x = env * sum(0.05 * np.exp(2j * np.pi * (700 + 75 * i) * t + 1j * rng.uniform(0, 6.3)) for i in range(16))
        x = x + (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 1e-3
        r = None
        for s in (4.0, 5.0, 6.0):
            r = lis.look(x[:int(s * RATE)])
            if r is not None:
                break
        self.assertIsNotNone(r)
        self.assertFalse(r.ok)


def frames(deltas, seconds, rng):
    """What _pitches would give for voiced frames whose combs sit at
    `deltas[i]` (audio Hz) during the i-th equal stretch of `seconds`, at
    pitches that wander like speech: (harmonicity, F0 index, rahmonics)."""
    n = int(seconds * RATE / at.HOP)
    k = rng.integers(100, 500, n)
    f0 = at._F0[k]
    delta = np.repeat(np.asarray(deltas, float), -(-n // len(deltas)))[:n]
    m = np.arange(1, len(at.RAHMONICS) + 1)[:, None]
    h = np.full(n, 0.5)
    return h, k, h * np.exp(-2j * np.pi * m * delta / f0)


class LookingAgainIsNotLuck(unittest.TestCase):
    """The rules a long listen adds to auto_tune()'s (see Listener)."""

    def test_a_later_voice_outweighing_the_first_is_refused_not_answered(self):
        # Two and a half seconds at one offset, then ten at another a pitch
        # away: both halves of the whole say the later one, but the first
        # four seconds by themselves say the earlier.
        h, k, c = frames([20.0, 140.0, 140.0, 140.0, 140.0], 12.5, np.random.default_rng(3))
        whole = at.judge(h, k, c)
        self.assertEqual(whole["why"], "")
        self.assertAlmostEqual(whole["delta"], 140.0, delta=3.0)
        parts = at.judge(h, k, c, part=int(at.PART_SECONDS * RATE / at.HOP))
        self.assertIn("at different times disagrees", parts["why"])

    def test_one_voice_throughout_passes_the_parts(self):
        h, k, c = frames([40.0], 12.0, np.random.default_rng(4))
        r = at.judge(h, k, c, part=int(at.PART_SECONDS * RATE / at.HOP))
        self.assertEqual(r["why"], "")
        self.assertEqual(len(r["parts"]), 3)
        self.assertAlmostEqual(r["delta"], 40.0, delta=3.0)

    def test_the_edge_never_chooses_between_a_near_fit_and_one_a_pitch_away(self):
        # Every other frame at +0 and at +200 Hz, the +200 ones a little
        # clearer: +200 fits best but puts the carrier nearer the voice than
        # MIN_EDGE_GAP, +0 almost as well. Refused at every look, and both
        # offered as guesses for the ear to choose (Engine._offer_guesses).
        h, k, c0 = frames([0.0], 12.0, np.random.default_rng(6))
        _, _, c1 = frames([200.0], 12.0, np.random.default_rng(6))
        odd = np.arange(len(h)) % 2 == 1
        h = np.where(odd, 0.51, 0.5)
        c = np.where(odd, c1 * 1.02, c0)
        for part in (0, int(at.PART_SECONDS * RATE / at.HOP)):
            r = at.judge(h, k, c, part=part)
            self.assertIn("nearer than a voice's own", r["why"])
            self.assertEqual(len(r["guesses"]), 2)
            self.assertAlmostEqual(r["guesses"][0], 200.0, delta=3.0)
            self.assertAlmostEqual(r["guesses"][1], 0.0, delta=3.0)

    def test_the_edge_only_ever_moves_towards_the_carrier(self):
        # The edge measured at each look (via coarse()) moves away from the
        # carrier and back: the listener keeps the nearest it has seen.
        x = station(5, 45.0, 10.0)
        lis = at.Listener("usb")
        real = at.coarse
        self.addCleanup(setattr, at, "coarse", real)
        seen = []
        for shift in (0.0, -13.0, 5.0):
            at.coarse = lambda iq, sb, rate=RATE, s=shift: (lambda c0, b, w: (c0 + s, b, w))(*real(iq[:FIRST], sb, rate))
            lis._hear(x[:FIRST + len(seen) * int(RATE)])
            seen.append(lis.edge())
        self.assertEqual(seen[1], seen[0] - 13.0)
        self.assertEqual(seen[2], seen[1])


if __name__ == "__main__":
    unittest.main()
