"""SSB auto-tune (ohscore/dsp/autotune.py): it lands a voice station from
either side, on both sidebands and at weak and strong signals, and refuses
- with a reason - what is not a voice it can measure."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore.devices import simsignals as sg
from ohscore.dsp import autotune as at

RATE = 12_000.0
N = int(at.CAPTURE_SECONDS * RATE)


def noise(rng, power):
    return (rng.standard_normal(N) + 1j * rng.standard_normal(N)) * np.sqrt(power / 2)


def station(seed, carrier, snr_db, sideband):
    """The simulator's voice (sg.voice: pitch moving syllable to syllable,
    300-2700 Hz) with its suppressed carrier `carrier` Hz from the dial, in
    white noise `snr_db` under its power, measured in 2.4 kHz."""
    rng = np.random.default_rng(seed)
    z = sg.voice(rng, 6.0)[:N].astype(np.complex128)
    if sideband == "lsb":
        z = np.conj(z)
    x = z * np.exp(2j * np.pi * carrier * np.arange(N) / RATE)
    ps = np.mean(np.abs(z) ** 2)
    return (x + noise(rng, ps / 10 ** (snr_db / 10) * RATE / 2400)).astype(np.complex64)


class Lands(unittest.TestCase):
    """Four voices per case, as an operator might press four times: it may
    refuse one (a voice can pause, or hold its pitch), but every answer it
    gives is within 10 Hz, and at least three are given."""

    def check(self, sideband, carrier, snr, seed):
        got = []
        for k in range(4):
            r = at.auto_tune(station(seed + 37 * k, carrier, snr, sideband), sideband)
            if r.ok:
                self.assertLess(abs(r.offset - carrier), 10.0, f"{sideband} {carrier:+.0f} Hz at {snr} dB: {r}")
                got.append(r)
        self.assertGreaterEqual(len(got), 3, f"{sideband} {carrier:+.0f} Hz at {snr} dB: refused too often")
        return got[0]

    def test_usb_from_either_side(self):
        for carrier in (-180.0, 45.0, 220.0):
            with self.subTest(carrier=carrier):
                self.check("usb", carrier, 10.0, 1000 + int(carrier))

    def test_lsb_from_either_side(self):
        for carrier in (-60.0, 220.0):
            with self.subTest(carrier=carrier):
                self.check("lsb", carrier, 10.0, 1000 + int(carrier))

    def test_weak_and_strong(self):
        for snr in (6.0, 20.0):
            with self.subTest(snr=snr):
                self.check("usb", -60.0, snr, 2000 + int(snr))

    def test_the_result_says_what_it_measured(self):
        r = self.check("usb", 45.0, 20.0, 3000)
        self.assertGreater(r.voiced, at.MIN_VOICED)
        self.assertTrue(90.0 < r.pitch < 260.0, r.pitch)
        self.assertLess(abs(r.coarse - 45.0), 150.0)


class Refuses(unittest.TestCase):
    def refused(self, x, sideband="usb"):
        r = at.auto_tune(x.astype(np.complex64), sideband)
        self.assertFalse(r.ok, f"took {r.offset:+.1f} Hz")
        self.assertTrue(r.why)
        return r.why

    def test_silence(self):
        self.assertIn("nothing near the dial", self.refused(noise(np.random.default_rng(1), 1e-4)))

    def test_a_carrier(self):
        rng = np.random.default_rng(2)
        t = np.arange(N) / RATE
        self.assertIn("carrier", self.refused(noise(rng, 1e-4) + 0.2 * np.exp(2j * np.pi * 700 * t)))

    def test_narrow_data_modes(self):
        rng = np.random.default_rng(3)
        for name, sig in (("psk31", sg.psk_like(rng, 5.0, 31.25, 1000.0)[:N]),
                          ("ft8", np.resize(sg.ft8_like(rng, 1200.0), N))):
            with self.subTest(mode=name):
                self.assertIn("data mode", self.refused(noise(rng, 1e-4) + 0.2 * sig))

    def test_rtty(self):
        rng = np.random.default_rng(4)
        self.assertIn("RTTY", self.refused(noise(rng, 1e-4) + 0.2 * sg.fsk_tones(rng, 5.0, 45.45, 170.0, 1500.0)[:N]))

    def test_the_middle_beacon(self):
        # 400 Bd BPSK, 1.6 kHz wide: a 200 Hz comb in its spectrum, as wide
        # as a voice, and taken for one on air before its steady level was
        # checked.
        rng = np.random.default_rng(6)
        t = np.arange(N) / RATE
        bpsk = sg.bpsk_beacon(rng, 5.0)[:N] * np.exp(2j * np.pi * 900 * t)
        for snr in (6.0, 20.0):
            with self.subTest(snr=snr):
                x = bpsk + noise(rng, 1.0 / 10 ** (snr / 10) * RATE / 2400)
                self.assertIn("level holds steady", self.refused(x))

    def test_a_voice_far_from_the_dial(self):
        self.assertIn("nothing near the dial", self.refused(station(1003, -4200.0, 20.0, "usb")))

    def test_evenly_spaced_tones(self):
        # A multi-carrier modem: a comb, but one whose spacing never moves,
        # so it cannot say which tooth is which.
        rng = np.random.default_rng(5)
        t = np.arange(N) / RATE
        tones = sum(0.05 * np.exp(2j * np.pi * (700 + 75 * i) * t
                                  + 1j * rng.uniform(0, 6.3, N // 600 + 1).repeat(600)[:N]) for i in range(16))
        self.refused(noise(rng, 1e-4) + tones)

    def test_not_a_voice_mode(self):
        r = at.auto_tune(station(1003, 0.0, 20.0, "usb"), "cw")
        self.assertFalse(r.ok)
        self.assertIn("USB or LSB", r.why)


class EdgeDecides(unittest.TestCase):
    """Offsets a pitch apart that fit almost equally (autotune.pick): the
    voice's edge rules out one that would put the carrier inside the voice
    (MIN_FOOT_GAP) and refuses to choose between one unusually near it
    (under MIN_EDGE_GAP) and one a pitch further; nothing decides when both
    are where a carrier usually is."""

    D = np.arange(at.FINE_SPAN[0], at.FINE_SPAN[1] + 0.25, 0.5)

    def votes(self, *peaks):
        """A summed vote with a peak (offset, height) per argument, 6 Hz
        wide, as voiced frame after voiced frame agreeing makes one."""
        return sum(h * np.exp(-0.5 * ((self.D - c) / 6.0) ** 2) for c, h in peaks) + 0.01

    def test_a_carrier_near_the_voice_and_one_a_pitch_lower_are_not_decided_by_the_edge(self):
        # +190 Hz (the carrier 110 Hz under the voice's edge) a little ahead
        # of +50 Hz, a pitch lower (250 Hz under it). On 07/10/2026 +50 was
        # one station's own leaked carrier; on 17/10/2026 stations whose
        # voice starts 70-90 Hz over their leaked carrier were landed a
        # pitch low by exactly this choice. Neither is taken on the edge's
        # word.
        v = self.votes((190.0, 1.0), (50.0, 0.95))
        _i, _delta, _rival, _allowed, why, decided = at.pick(self.D, v)
        self.assertIn("nearer than a voice's own", why)
        self.assertEqual(decided, "")

    def test_a_fit_inside_the_voice_is_never_the_carrier(self):
        # With the voice's edge at +250, +230 puts the carrier 20 Hz under
        # it: no transmitter passes that. +100, a pitch lower and nearly as
        # good, is the answer.
        v = self.votes((230.0, 1.0), (100.0, 0.9))
        _i, delta, _rival, _allowed, why, _decided = at.pick(self.D, v, edge=250.0)
        self.assertAlmostEqual(delta, 100.0, delta=1.0)
        self.assertEqual(why, "")

    def test_a_fit_inside_the_voice_far_ahead_is_refused_not_moved(self):
        v = self.votes((230.0, 1.0), (100.0, 0.5))
        _i, _delta, _rival, _allowed, why, _decided = at.pick(self.D, v, edge=250.0)
        self.assertIn("nearer than a voice's own", why)

    def test_both_where_a_carrier_can_be_still_ties(self):
        v = self.votes((-60.0, 1.0), (80.0, 0.95))
        i, _delta, rival, _allowed, why, decided = at.pick(self.D, v)
        self.assertGreater(rival / v[i], at.MAX_RIVAL)
        self.assertEqual((why, decided), ("", ""))

    def test_a_clear_answer_too_near_the_edge_is_refused_not_moved(self):
        # Nothing the voice hardly voted for is promoted: with the best
        # fit out of the edge's reach and well ahead, it says so.
        v = self.votes((190.0, 1.0), (50.0, 0.5))
        _i, _delta, _rival, _allowed, why, _decided = at.pick(self.D, v)
        self.assertIn("nearer than a voice's own", why)

    def test_a_clear_answer_the_edge_allows_is_left_alone(self):
        v = self.votes((40.0, 1.0), (180.0, 0.6))
        _i, delta, _rival, _allowed, why, decided = at.pick(self.D, v)
        self.assertAlmostEqual(delta, 40.0, delta=1.0)
        self.assertEqual((why, decided), ("", ""))

if __name__ == "__main__":
    unittest.main()
