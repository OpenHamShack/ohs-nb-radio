import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from helpers import sim_cfg
from ohscore.devices import simsignals as sg
from ohsnb import bandplan
from ohsnb.devices.sim import FT8Activity, Presence, SimDevice


def spectrum(x, fs):
    n = len(x)
    w = np.hanning(n)
    P = np.fft.fftshift(np.abs(np.fft.fft(x * w)) ** 2) / w.sum() ** 2
    f = np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
    return f, P


class SimBeacons(unittest.TestCase):
    def test_beacons_where_the_lnb_error_puts_them(self):
        d = SimDevice(sim_cfg(simRxErrorHz=12_345.0))
        d.open()
        x = np.concatenate([d.read(90_000) for _ in range(14)])[:2 ** 20]
        f, P = spectrum(x, d.fs)

        def off(dl):
            return dl - d.lnb_lo + 12_345.0 - d.rx_if

        # Lower beacon: the F1A space tone at x.500000 and mark at +400 Hz.
        for tone in (bandplan.BEACONS["lower"]["dl"], bandplan.BEACONS["lower"]["dl"] + 400):
            sel = np.abs(f - off(tone)) < 100
            self.assertLess(abs(f[sel][np.argmax(P[sel])] - off(tone)), 2.0)
        # Middle beacon: carrier-less BPSK - nothing at the carrier, but its
        # square has a line at twice the carrier offset.
        f2, P2 = spectrum(x * x, d.fs)
        want = 2 * off(bandplan.BEACONS["middle"]["dl"])
        sel = np.abs(f2 - want) < 200
        self.assertLess(abs(f2[sel][np.argmax(P2[sel])] - want), 2.0)
        self.assertGreater(P2[sel].max() / np.median(P2[sel]), 100)

    def test_own_transmission_comes_back_late_and_offset(self):
        d = SimDevice(sim_cfg(simUlErrorHz=-1234.0))
        d.open()
        lo = bandplan.UL_LO - 30_000.0
        d.set_tx_freq(lo)
        d.set_tx_gain(-20.0)
        d.tx_start()
        L = d.geo.L
        # A carrier 100 kHz above the TX LO, i.e. uplink 2400.070.
        t = np.arange(5 * L) / d.fs
        tone = (0.9 * np.exp(2j * np.pi * 100_000.0 * t)).astype(np.complex64)
        expect = (lo + 100_000.0 - 1234.0 + bandplan.TRANSPONDER_LO) - d.lnb_lo + d.rx_err0 - d.rx_if
        got = []
        for _ in range(8):                        # 0.6 s
            d.write(tone)
            got.append(d.read(5 * L))
        d.tx_stop()
        x = np.concatenate(got)
        tt = np.arange(len(x)) / d.fs
        ref = np.exp(-2j * np.pi * expect * tt)
        early = np.abs(np.mean((x * ref)[: int(0.2 * d.fs)]))
        late = np.abs(np.mean((x * ref)[int(0.35 * d.fs):]))
        self.assertLess(early, late / 30)          # nothing before the round trip
        # At simRefGainDb the carrier equals the beacon level (-40 dBFS), x0.9.
        self.assertAlmostEqual(20 * np.log10(late), -40 + 20 * np.log10(0.9), delta=0.5)


class Templates(unittest.TestCase):
    """The signal templates both simulators build their stations from."""

    def test_fast_len_is_the_next_length_with_only_small_factors(self):
        def smooth(k):
            for p in (2, 3, 5):
                while k % p == 0:
                    k //= p
            return k == 1
        for n in list(range(1, 2000)) + [239_999, 383_997, 151_681]:
            got = sg.fast_len(n)
            self.assertGreaterEqual(got, n)
            self.assertTrue(smooth(got), (n, got))
            self.assertFalse(any(smooth(k) for k in range(n, got)), n)

    def test_a_voice_is_its_asked_length_and_band_limited_upper_sideband(self):
        rng = np.random.default_rng(3)
        for seconds in (20.7, 27.31, 31.9):
            z = sg.voice(rng, seconds)
            self.assertAlmostEqual(len(z) / sg.RATE, seconds, delta=seconds * 0.01)
            f, P = spectrum(z, sg.RATE)
            total = P.sum()
            self.assertGreater(P[(f > 300) & (f < 2700)].sum() / total, 0.99)
            self.assertLess(P[f < 0].sum() / total, 0.01)


class PresenceSchedule(unittest.TestCase):
    """Presence drives whether a station is rendered at all (SimDevice skips
    a silent one before it reaches the synthesiser), so its gain() is worth
    testing directly - a station's arrival/departure is a fade, not a click,
    and it must repeat the same way every cycle."""

    def test_on_window_fades_in_and_out_and_is_silent_between_windows(self):
        rng = np.random.default_rng(42)
        p = Presence(rng, (60.0, 120.0), (30.0, 60.0), cycle_s=600.0, fade_s=2.0)
        a, b = p.windows[0]
        self.assertEqual(p.gain(a), 0.0)                      # fade just starting
        self.assertAlmostEqual(p.gain(a + 1.0), 0.5, places=3)
        self.assertEqual(p.gain(a + 2.0), 1.0)                # fade complete
        self.assertEqual(p.gain((a + b) / 2), 1.0)
        self.assertAlmostEqual(p.gain(b - 1.0), 0.5, places=3)
        self.assertEqual(p.gain(b), 0.0)
        self.assertEqual(p.gain(a - 5.0), 0.0)                # firmly off, between windows

    def test_repeats_every_cycle(self):
        rng = np.random.default_rng(7)
        p = Presence(rng, (60.0, 90.0), (40.0, 80.0), cycle_s=500.0, fade_s=1.0)
        for t in (12.0, 88.0, 240.0, 499.0):
            self.assertEqual(p.gain(t), p.gain(t + 500.0))
            self.assertEqual(p.gain(t), p.gain(t + 5 * 500.0))

    def test_something_is_usually_already_under_way_at_t0(self):
        # With a start drawn only from [0, off_range[1]] (the old behaviour),
        # nothing could be active before its first window - so for the first
        # couple of minutes after the sim opens, every station rolled the
        # same way: silent. Allowing a negative start (already mid-contact
        # when the sim opens) fixes that; over many stations, most cycles
        # should have one already on air at t=0.
        on_at_zero = sum(Presence(np.random.default_rng(seed), (90.0, 300.0), (60.0, 600.0)).gain(0.0) > 0
                         for seed in range(200))
        self.assertGreater(on_at_zero, 30)        # on/(on+off) ~ 28% of 200, comfortably over a floor of 15%


class Population(unittest.TestCase):
    """The simulated band is sized and placed like a real QO-100 NB weekend
    evening (DESIGN.md); these check the roster this seed produces, not any
    particular signal's content."""

    def _open(self, seed=5):
        d = SimDevice(sim_cfg(simSignals=True, simSeed=seed))
        d.open()
        return d

    def test_ssb_cw_psk_rtty_counts_and_segments(self):
        d = self._open()
        ssb_names = {s.name for s in d.stations if s.name.startswith("SSB")}
        cw = [s for s in d.stations if s.name.startswith("CW")]
        psk = [s for s in d.stations if s.name.startswith("PSK31")]
        rtty = [s for s in d.stations if s.name.startswith("RTTY")]
        self.assertTrue(15 <= len(ssb_names) <= 30, ssb_names)       # one real evening's worth of QSOs
        self.assertTrue(6 <= len(cw) <= 8, len(cw))
        self.assertEqual(len(psk), 3)
        self.assertEqual(len(rtty), 2)
        for s in d.stations:
            if not (s.name.startswith("SSB") or s.name.startswith("CW")):
                continue
            seg = bandplan.segment_at(s.dl)
            self.assertIsNotNone(seg, (s.name, s.dl))
            want = "cw" if s.name.startswith("CW") else "ssb"
            self.assertIn(want, seg["modes"], (s.name, s.dl, seg))   # never placed somewhere it can't run

    def test_ssb_qso_halves_share_one_dial_and_opposite_talk_windows(self):
        # "SSB 10489.700" etc. appears exactly twice: the two ends of the QSO.
        d = self._open()
        ssb = [s for s in d.stations if s.name.startswith("SSB")]
        from collections import Counter
        counts = Counter(s.name for s in ssb)
        self.assertTrue(counts)
        self.assertTrue(all(c == 2 for c in counts.values()), counts)

    def test_most_stations_come_and_go_rather_than_running_forever(self):
        d = self._open()
        gated = [s for s in d.stations if not isinstance(s, FT8Activity) and s.presence is not None]
        self.assertGreater(len(gated), 40)         # the roster this population is sized for
        counts = [sum(1 for s in gated if s.presence.gain(float(t)) > 0) for t in range(0, 7200, 30)]
        self.assertGreater(min(counts), 0)         # the band is never completely dead
        self.assertLess(max(counts), len(gated))   # ...nor is everyone on at once
        self.assertGreater(len(set(counts)), 10)   # and it visibly turns over, not just two states

    def test_a_gated_station_contributes_nothing_while_off(self):
        """Behaviour, not bookkeeping: read actual IQ either side of a known
        SSB station's own on/off edge and check its frequency really does
        go quiet, not just that Presence.gain() says so. The roster is
        trimmed to this one station (plus the beacons, which are at known,
        well-separated frequencies): the real population packs 15-30 QSOs in
        close enough that a neighbour's sidelobes can land in a 2.4 kHz
        passband next door, which would make this a test of crowding, not
        of the gate."""
        d = self._open()
        # The loudest SSB station, not just the first: voice()'s syllabic
        # envelope means even an "on" station is only loud some of the time
        # (that's realistic - a real waterfall flickers with speech, it
        # doesn't paint a solid bar), so a quiet one gives an on/off contrast
        # too marginal to assert on reliably. The gate under test doesn't
        # care which station it's gating.
        st = max((s for s in d.stations if s.name.startswith("SSB")), key=lambda s: s.amp)
        d.stations = [s for s in d.stations if s is st or "beacon" in s.name]
        # Two consecutive windows with a gap wide enough to sample cleanly
        # inside it (the off_range can be as short as 20 s), comfortably
        # inside the test window.
        w = st.presence.windows
        (prev_end, (on_a, on_b)) = next((w[i][1], w[i + 1]) for i in range(len(w) - 1)
                                        if 60.0 < w[i + 1][0] < 3000.0 and w[i + 1][0] - w[i][1] > 15.0)
        # A full second, not one ~15 ms block: voice() has gaps between
        # syllables, so a single block can land in one and look silent even
        # while on - a second is several syllables, long enough to average
        # the envelope rather than catch one slice of it.
        dur = 1.0
        n = int(dur * d.fs)
        d.n = int(((prev_end + on_a) / 2 - dur / 2) * d.fs)   # a second squarely inside the gap
        off_block = d.read(n)
        d.n = int(((on_a + on_b) / 2 - dur / 2) * d.fs)       # a second mid-contact
        on_block = d.read(n)
        f, p_off = spectrum(off_block, d.fs)
        _, p_on = spectrum(on_block, d.fs)
        # voice() is analytic (one-sided, like a real USB transmitter): its
        # energy sits 300-2700 Hz above the dial, not on it, and moves around
        # within that band syllable to syllable - so this sums the whole
        # occupied band rather than checking one narrow, possibly-silent slice.
        carrier_hz = st.dl - d.lnb_lo + d.rx_err0 - d.rx_if
        sel = (f > carrier_hz + 300.0) & (f < carrier_hz + 2700.0)
        self.assertGreater(p_on[sel].sum() / p_off[sel].sum(), 8.0)   # unmistakably louder once it's on


if __name__ == "__main__":
    unittest.main()
