"""ohsnb.analyse_power: over-power events (a downlink stronger than the
middle beacon) and the LEILA siren check - behavioural, not textual:
built signals of known strength and known frequency, checked against what
the real function reports, not against any string in its source."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohsnb import analyse_power, bandplan

FS = 1_200_000.0


def _wideband(n, dc0, rng_seed, extra=None):
    """Noise plus a weak middle-beacon stand-in (just a tone at the
    beacon's own reference frequency - all _line_hits needs it for is a
    level to compare candidates against, not a real BPSK waveform) plus
    whatever `extra` (dc0-relative complex baseband, same length) adds."""
    mid_ref = bandplan.BEACONS["middle"]["ref"]
    rng = np.random.default_rng(rng_seed)
    t = np.arange(n) / FS
    noise = 0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    beacon = 0.05 * np.exp(2j * np.pi * (mid_ref - dc0) * t)
    x = noise + beacon
    if extra is not None:
        x = x + extra
    return x.astype(np.complex64)


def _view(x):
    return np.stack([x.real, x.imag], axis=1).astype(np.float32)


class OverpowerEvents(unittest.TestCase):
    def setUp(self):
        self.dc0 = (bandplan.DL_LO + bandplan.DL_HI) / 2.0
        self.caps = [{"core:sample_start": 0, "core:frequency": self.dc0}]
        self.info = {"lnb_lo_hz": None, "nominal_dc_flat": None}

    def test_noise_and_a_weak_beacon_alone_raise_no_event(self):
        n = int(20.0 * FS)
        x = _wideband(n, self.dc0, 11)
        r = analyse_power.overpower_events(_view(x), 1.0, n, FS, self.caps, self.info, 0.0, [],
                                           leila_check=False)
        self.assertEqual(r["events"], [])

    def test_a_sustained_strong_signal_is_found_where_and_how_strong_it_is(self):
        n = int(20.0 * FS)
        t = np.arange(n) / FS
        hot_abs = bandplan.DL_LO + 300_000.0     # well clear of every beacon's guard zone
        hot = 0.4 * np.exp(2j * np.pi * (hot_abs - self.dc0) * t)    # ~18 dB over the 0.05-amplitude beacon
        x = _wideband(n, self.dc0, 12, extra=hot)
        r = analyse_power.overpower_events(_view(x), 1.0, n, FS, self.caps, self.info, 0.0, [],
                                           leila_check=False)
        self.assertEqual(len(r["events"]), 1)
        e = r["events"][0]
        self.assertAlmostEqual((e["freq_lo_hz"] + e["freq_hi_hz"]) / 2, hot_abs, delta=50.0)
        self.assertGreater(e["max_excess_db"], 10.0)
        self.assertGreaterEqual(e["duration_s"], 15.0)      # most of the 20 s file, allowing for warm-up/cool-down

    def test_the_default_run_also_attempts_the_leila_check(self):
        # leila_check defaults to True: this is the path
        # tests/test_analyse_power.py's other cases all opt out of (and
        # the one ohsnb --analyse itself takes) - it must run to
        # completion and say something, not raise. Caught a real bug
        # (_dc_for_t called with the wrong arguments) that every other
        # test here, all passing leila_check=False, missed entirely.
        n = int(20.0 * FS)
        t = np.arange(n) / FS
        hot_abs = bandplan.DL_LO + 300_000.0
        hot = 0.4 * np.exp(2j * np.pi * (hot_abs - self.dc0) * t)
        x = _wideband(n, self.dc0, 14, extra=hot)
        r = analyse_power.overpower_events(_view(x), 1.0, n, FS, self.caps, self.info, 0.0, [])
        self.assertEqual(len(r["events"]), 1)
        e = r["events"][0]
        self.assertIn(e["leila_like"], (True, False))     # answered, not left None
        self.assertTrue(e["leila_why"])

    def test_a_brief_blip_under_the_duration_floor_is_not_an_event(self):
        n = int(20.0 * FS)
        t = np.arange(n) / FS
        hot_abs = bandplan.DL_LO + 300_000.0
        env = np.zeros(n)
        env[int(5.0 * FS):int(5.6 * FS)] = 1.0     # 0.6 s, under MIN_DURATION_S (2.0 s)
        hot = 0.4 * env * np.exp(2j * np.pi * (hot_abs - self.dc0) * t)
        x = _wideband(n, self.dc0, 13, extra=hot)
        r = analyse_power.overpower_events(_view(x), 1.0, n, FS, self.caps, self.info, 0.0, [],
                                           leila_check=False)
        self.assertEqual(r["events"], [])


class LeilaCheck(unittest.TestCase):
    """analyse_power._leila_check directly: LEILA's siren as measured on the
    17/10/2026 recordings (two tones 205 Hz apart, 200 ms each) on the
    event's frequency is found; a steady carrier, and the swept warble the
    check looked for before those recordings, are not. The real sirens
    themselves are tests/test_overpower.py's."""

    def setUp(self):
        self.dc0 = (bandplan.DL_LO + bandplan.DL_HI) / 2.0
        self.f_abs = bandplan.DL_LO + 300_000.0
        self.n = int(8.0 * FS)
        self.t = np.arange(self.n) / FS
        rng = np.random.default_rng(21)
        self.noise = 0.01 * (rng.standard_normal(self.n) + 1j * rng.standard_normal(self.n))

    def _run(self, sig):
        view = _view((self.noise + sig).astype(np.complex64))
        return analyse_power._leila_check(view, 1.0, FS, self.dc0, 0.0, self.f_abs - 50.0, self.f_abs + 250.0,
                                          0.5, 2.0)

    def test_the_two_tone_siren_is_found(self):
        rel = np.maximum(self.t - 2.0, 0.0)
        upper_time = np.floor(rel / 0.4) * 0.2 + np.maximum(rel % 0.4 - 0.2, 0.0)
        ph = 2 * np.pi * ((self.f_abs - self.dc0) * self.t + 205.0 * upper_time)
        on = (self.t >= 2.0) & (self.t < 7.0)
        res = self._run(0.4 * on * np.exp(1j * ph))
        self.assertTrue(res["leila_like"], res["why"])

    def test_a_steady_carrier_is_not(self):
        res = self._run(0.4 * np.exp(2j * np.pi * (self.f_abs - self.dc0) * self.t))
        self.assertFalse(res["leila_like"])

    def test_a_swept_warble_is_not(self):
        ph = 2 * np.pi * (self.f_abs + 100.0 - self.dc0) * self.t + 600.0 * np.sin(2 * np.pi * 0.5 * self.t)
        res = self._run(0.4 * np.exp(1j * ph))
        self.assertFalse(res["leila_like"])


class EventsCloseAndStayClosed(unittest.TestCase):
    """The tracker's open list must shrink again once a signal goes away,
    and a closed event must be reported once. Until 08/10/2026 neither held
    (a closed event stayed open and was re-appended to `closed` every line
    after): 127,029 "events" from 10 minutes of a busy real recording, and
    the LEILA check reading each copy's IQ ran a 3-hour --extended run out
    of 58 GB. Every synthetic test passed regardless, because none had a
    signal that stopped."""

    def test_bursts_that_come_and_go_are_closed_once_each_and_open_stays_small(self):
        tr = analyse_power._Tracker()
        bursts = 0
        max_open = 0
        # 200 stations in turn, each on for 5 lines and then silent - the
        # shape of an evening's FT8/SSB traffic, not one steady carrier.
        for k in range(200):
            f = 10_489_600_000.0 + (k % 7) * 50.0     # the same few frequencies, reused
            for line in range(5):
                tr.add_line([(f, f + 40.0, 6.0)], float(k * 10 + line))
            bursts += 1
            for line in range(5, 10):
                tr.add_line([], float(k * 10 + line))
            max_open = max(max_open, len(tr.open))
        events = tr.finish()
        self.assertLessEqual(max_open, 1)
        self.assertEqual(len(events), bursts)
        self.assertEqual(len({id(e) for e in events}), len(events))     # no event reported twice
        self.assertTrue(all(e["t_last"] - e["t_start"] == 4.0 for e in events))

    def test_a_signal_back_after_a_long_gap_is_a_second_event_not_the_first_revived(self):
        n = int(30.0 * FS)
        dc0 = (bandplan.DL_LO + bandplan.DL_HI) / 2.0
        t = np.arange(n) / FS
        hot_abs = bandplan.DL_LO + 300_000.0
        on = ((t >= 2.0) & (t < 9.0)) | ((t >= 20.0) & (t < 27.0))
        hot = 0.4 * np.exp(2j * np.pi * (hot_abs - dc0) * t) * on
        x = _wideband(n, dc0, 15, extra=hot)
        caps = [{"core:sample_start": 0, "core:frequency": dc0}]
        r = analyse_power.overpower_events(_view(x), 1.0, n, FS, caps, {"lnb_lo_hz": None, "nominal_dc_flat": None},
                                           0.0, [], leila_check=False)
        self.assertEqual(len(r["events"]), 2)
        first, second = sorted(r["events"], key=lambda e: e["t_start_s"])
        self.assertLess(first["t_end_s"], 12.0)
        self.assertGreater(second["t_start_s"], 18.0)


class LeilaCheckMemory(unittest.TestCase):
    """_leila_check over a long event holds a block of IQ at a time, not
    the event's whole span: it once read the span in one piece, which for
    an hours-long carrier is more memory than the machine has."""

    def test_a_long_event_is_checked_in_bounded_memory(self):
        import tracemalloc
        fs = 120_000.0          # a narrow test rate: 60 s is 7.2 M samples, ~58 MB as complex64
        n = int(60.0 * fs)
        f_rel = 10_000.0
        t = np.arange(n) / fs
        x = (0.4 * np.exp(2j * np.pi * f_rel * t)).astype(np.complex64)
        view = _view(x)
        del x, t
        dc = 10_489_500_000.0
        tracemalloc.start()
        try:
            res = analyse_power._leila_check(view, 1.0, fs, dc, 0.0, dc + f_rel - 100.0, dc + f_rel + 100.0,
                                             1.0, 59.0)
            _cur, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertFalse(res["leila_like"])         # a steady carrier, checked end to end
        self.assertTrue(res["why"])
        # The whole span as complex64 alone would be ~55 MB; a block at a
        # time is a few MB whatever the event's length.
        self.assertLess(peak, 16 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
