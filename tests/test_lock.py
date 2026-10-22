"""Beacon lock and TX lock, end to end through the simulated transponder."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

from helpers import make_radio, noise_audio, run_sim, sim_cfg, wait_rx_lock
from ohsnb import bandplan
from ohsnb.devices.sim import SimDevice
from ohscore.dsp.bank import Analysis
from ohsnb.dsp.lock import BeaconTracker


def track(choice, rx_err, drift, seconds, drop=None, seed=3):
    """Run a BeaconTracker against the sim; return (errors after settling,
    beacons used, final state)."""
    d = SimDevice(sim_cfg(simSeed=seed, simRxErrorHz=rx_err, simDriftHz=drift, simDriftSec=120.0))
    d.open()
    if drop:
        d.stations = [s for s in d.stations if s.name != drop]
    an = Analysis(d.geo)
    tr = BeaconTracker(d.geo, choice, 50_000.0, 0.0)
    errs, used = [], set()
    n = 0
    for _ in range(int(seconds * d.fs / 90_000)):
        x = d.read(90_000)
        n += len(x)
        t = n / d.fs
        X, st = an.push(x)
        r = tr.process(X, st, d.rx_if, d.lnb_lo, t)
        if r and t > 5 and r["state"] == "locked":
            errs.append(tr.rx_corr - d.rx_err(t))
            used.add(r.get("used"))
    return np.array(errs), used, tr.state


class BeaconLock(unittest.TestCase):
    def test_acquires_a_big_lnb_error_and_follows_drift_within_5_hz(self):
        # 23 kHz off (an unmodified LNB), wandering +-300 Hz on a 2-minute
        # cycle - up to ~22 Hz/s, far faster than a real LNB warms.
        errs, used, st = track("middle", 23_456.0, 300.0, 60)
        self.assertEqual(st, "locked")
        self.assertGreater(len(errs), 80)
        self.assertLess(np.max(np.abs(errs)), 5.0)
        self.assertEqual(used, {"middle"})

    def test_lower_beacon_lock(self):
        errs, used, st = track("lower", -31_000.0, 300.0, 40)
        self.assertLess(np.max(np.abs(errs)), 5.0)
        self.assertEqual(used, {"lower"})

    def test_falls_back_to_the_other_beacon(self):
        errs, used, _ = track("middle", 4_000.0, 0.0, 20, drop="middle beacon")
        self.assertEqual(used, {"lower"})
        self.assertLess(np.max(np.abs(errs)), 2.0)

    def test_silence_is_no_beacon_not_a_failure(self):
        # Exact zeros: what a recording plays after its end, and what a
        # stalled radio can deliver. The search's level ratios were 0 / 0.
        d = SimDevice(sim_cfg())
        an = Analysis(d.geo)
        tr = BeaconTracker(d.geo, "middle", 50_000.0, 0.0)
        for k in range(30):
            X, st = an.push(np.zeros(90_000, np.complex64))
            tr.process(X, st, d.rx_if, d.lnb_lo, (k + 1) * 0.075)
        self.assertNotEqual(tr.state, "locked")


MIDDLE = bandplan.BEACONS["middle"]["ref"]


def look(rx_err, seconds, extras=(), search=50_000.0, choice="middle", events=(), seed=3, beacons_db=0.0,
         drift=0.0, hops=None):
    """Run a BeaconTracker on the sim with `extras` - (kind, downlink,
    dBFS) for SimDevice.add_station - on the band, and `events` - (when,
    fn(device)), `when` a time or a test of (time, tracker) - happening on
    the way, each once; the LNB wandering +-`drift` Hz over two minutes,
    and with `hops` - (Hz, every s, from s, until s) - its LO jumping
    between Hz/2 and Hz either side of that, every so often, for a while.
    Returns (tracker, reports, the tracker's error against the sim's LNB
    at each locked report after 1 s). Each report carries the tracker's
    `why` as it stood."""
    d = SimDevice(sim_cfg(simSeed=seed, simRxErrorHz=rx_err, simDriftHz=drift, simDriftSec=120.0))
    d.open()
    if hops:
        amp, every, t0, t1 = hops
        k = int((min(t1, seconds) - t0) / every) + 2
        # Alternating, so each hop is a real one (amp/2 to amp from 0, on
        # the other side from the last), not two draws that happen to agree.
        jump = np.random.default_rng(seed).uniform(amp / 2, amp, k) * np.where(np.arange(k) % 2, 1.0, -1.0)
        smooth = d.rx_err
        d.rx_err = lambda t: smooth(t) + (jump[int((t - t0) / every)] if t0 <= t < t1 else 0.0)
    for st in d.stations:
        if "beacon" in st.name:
            st.amp *= 10 ** (beacons_db / 20)
    for kind, dl, db in extras:
        d.add_station(kind, dl, db)
    an = Analysis(d.geo)
    tr = BeaconTracker(d.geo, choice, search, 0.0)
    reps, errs = [], []
    todo = list(events)
    n = 0
    while n < seconds * d.fs:
        t = n / d.fs
        for ev in list(todo):
            when, fn = ev
            if (when(t, tr) if callable(when) else when <= t):
                fn(d)
                todo.remove(ev)
        x = d.read(90_000)
        n += len(x)
        X, st = an.push(x)
        r = tr.process(X, st, d.rx_if, d.lnb_lo, n / d.fs)
        if r:
            reps.append((n / d.fs, {**r, "why": tr.why}))
            if r["state"] == "locked" and n / d.fs > 1.0:
                errs.append(tr.rx_corr - d.rx_err(n / d.fs))
    return tr, reps, np.array(errs)


def drop(name):
    def fn(d):
        d.stations = [s for s in d.stations if s.name != name]
    return fn


class NotTheBeacon(unittest.TestCase):
    """What took beacon lock off the middle beacon, or could: each was
    locked to before the detector learnt what only the beacon has
    (ohsnb/dsp/lock.py, "what only the middle beacon has")."""

    def test_a_loud_voice_beside_the_middle_beacon_is_refused(self):
        # Ray, 05/10: SSB next to the middle beacon pulled the lock onto it.
        # Sustained vowels 12 dB over a beacon 10 dB down on the default,
        # 5.3 kHz below it; LNB 27 kHz out, as his. Before: locked 4.6 kHz
        # off, on the voice, every time.
        for side, kind in ((-5_300.0, "usb"), (5_300.0, "lsb")):
            tr, reps, errs = look(-27_000.0, 12, [(kind, MIDDLE + side, -38.0)], beacons_db=-10.0)
            self.assertEqual(tr.state, "locked")
            self.assertLess(np.max(np.abs(errs)), 5.0)
            refused = [w for _, r in reps for w in r.get("rejected", [])]
            self.assertTrue(any("speech" in w for w in refused), refused)

    def test_a_voice_far_louder_than_the_beacon_still_leaves_it_found(self):
        # 24 dB over the beacon: a voice makes a dozen squared lines, and
        # they must not use up every look before the beacon's turn.
        tr, _, errs = look(-27_000.0, 8, [("usb", MIDDLE - 5_300.0, -26.0)], beacons_db=-10.0)
        self.assertEqual(tr.state, "locked")
        self.assertLess(np.max(np.abs(errs)), 5.0)

    def test_a_carrier_as_loud_as_the_beacon_is_refused(self):
        # Squared, a carrier is a purer line than the beacon's. Before:
        # locked 57 kHz off, on the carrier, 30 kHz from the search centre.
        tr, reps, errs = look(-27_000.0, 8, [("carrier", MIDDLE + 30_000.0 + 27_000.0, -34.0)])
        self.assertLess(np.max(np.abs(errs)), 5.0)
        refused = [w for _, r in reps for w in r.get("rejected", [])]
        self.assertTrue(any("single line" in w for w in refused), refused)

    def test_widening_to_55_khz_lets_in_no_more_than_the_beacon(self):
        # Ray, 05/10: lock worse at +-55 kHz than at +-50. A carrier 52 kHz
        # from the search centre is outside +-50 and inside +-55; before,
        # +-55 locked to it (79 kHz off) and +-50 did not.
        for search in (50_000.0, 55_000.0):
            _, _, errs = look(-27_000.0, 8, [("carrier", MIDDLE + 52_000.0 + 27_000.0, -40.0)], search=search)
            self.assertLess(np.max(np.abs(errs)), 5.0, search)

    def test_signals_outside_the_search_do_not_fold_into_it(self):
        # Squaring doubles the bandwidth: a carrier 85 kHz out came back
        # at -70 kHz, read as a beacon 35 kHz off. Now none is seen there.
        _, reps, _ = look(-27_000.0, 3, [("carrier", MIDDLE + 85_000.0 + 27_000.0, -34.0)])
        first = reps[0][1]
        self.assertAlmostEqual(first["found"]["middle"], -27_000.0, delta=5.0)

    def test_a_second_bpsk_beacon_loses_to_the_lower_beacon_s_word(self):
        # A copy of the middle beacon, louder, 20 kHz away: nothing in the
        # signal tells them apart, but the lower beacon is 250 kHz below
        # the real one and contradicts the copy. Before: locked to the copy.
        tr, reps, errs = look(-27_000.0, 8, [("bpsk", MIDDLE - 20_000.0, -34.0)])
        self.assertLess(np.max(np.abs(errs)), 5.0)
        refused = [w for _, r in reps for w in r.get("rejected", [])]
        self.assertTrue(any("disagrees with the lower beacon" in w for w in refused), refused)

    def test_a_lost_beacon_is_looked_for_where_it_was_first(self):
        # The middle beacon goes (the lower is not on this band), and a
        # louder BPSK copy is 20 kHz away all along. Ten seconds after
        # losing it, beacon lock searches again; the beacon is back 1.5 s
        # into that. Before: the search was full-width at once, and the
        # copy - the strongest line in it - was locked to within a second.
        beacon, lost, gave_up = [], [], []

        def hide(d):
            beacon[:] = [s for s in d.stations if s.name == "middle beacon"]
            drop("middle beacon")(d)

        def searching_again(t, tr):
            if tr.state == "lost":
                lost.append(t)
            if lost and not gave_up and tr.state == "searching":
                gave_up.append(t)
            return bool(gave_up) and t >= gave_up[0] + 1.5

        tr, reps, errs = look(-27_000.0, 32, events=[
            (0.0, drop("lower beacon")), (4.0, lambda d: d.add_station("bpsk", MIDDLE - 20_000.0, -34.0)),
            (6.0, hide), (searching_again, lambda d: d.stations.extend(beacon))])
        self.assertTrue(gave_up)
        self.assertEqual(tr.state, "locked")
        self.assertLess(np.max(np.abs(errs)), 5.0)
        self.assertLess(abs(tr.rx_corr + 27_000.0), 5.0)


def beacons_at(db):
    """An event: both beacons `db` dB from the simulator's own level."""
    def fn(d):
        for s in d.stations:
            if "beacon" in s.name:
                s.orig_amp = getattr(s, "orig_amp", s.amp)
                s.amp = s.orig_amp * 10 ** (db / 20)
    return fn


# A dish like Brian's on 07/10/2026: the middle beacon 9-11 dB over the
# noise, wandering either side of beacon lock's 10 dB, and the LNB drifting
# 3 Hz/s. Acquired at full strength, faded over 5 s (as a dish moved off
# the peak, or a wet one), then 1 dB either side of 10 dB every 2 s.
WEAK = -20.5        # the simulator's middle beacon reads ~10 dB here
WOBBLE = [(4.0 + 0.5 * k, beacons_at(WEAK * (k + 1) / 10)) for k in range(10)] + \
         [(10.0 + 2.0 * k, beacons_at(WEAK + (1.0 if k % 2 else -1.0))) for k in range(20)]


def flips(reps, after):
    st = [r["state"] for t, r in reps if t > after]
    return st, sum(1 for a, b in zip(st, st[1:]) if (a == "locked") != (b == "locked"))


class WeakBeacon(unittest.TestCase):
    """Beacon lock's hysteresis (BeaconTracker.HOLD_SNR): a weak beacon is
    held through normal variation, and nothing that is not the beacon
    keeps a lock it had."""

    def test_a_beacon_wandering_round_the_threshold_stays_locked(self):
        tr, reps, errs = look(-27_000.0, 50, events=WOBBLE, drift=60.0)
        st, n = flips(reps, 10.0)
        snr = [r["beacons"]["middle"]["snr"] for t, r in reps if t > 10.0 and "beacons" in r]
        self.assertLess(min(snr), BeaconTracker.LOCK_SNR)          # the data does go under the threshold
        self.assertGreater(min(snr), BeaconTracker.HOLD_SNR)
        self.assertEqual(n, 0, st)
        self.assertEqual(set(st), {"locked"})
        self.assertLess(np.max(np.abs(errs)), 5.0)                  # and it followed the drift

    def test_without_the_hysteresis_the_same_beacon_flips(self):
        # The regression the data above reproduces: one threshold for both
        # (as before), and the lock comes and goes as the level wanders.
        with mock.patch.object(BeaconTracker, "HOLD_SNR", BeaconTracker.LOCK_SNR):
            _, reps, _ = look(-27_000.0, 50, events=WOBBLE, drift=60.0)
        st, n = flips(reps, 10.0)
        self.assertGreaterEqual(n, 4, st)
        self.assertIn("lost", st)

    def test_a_beacon_too_weak_to_steer_by_is_lost(self):
        tr, reps, _ = look(-27_000.0, 16, events=[(4.0, beacons_at(-32.0))])
        st, _ = flips(reps, 7.0)
        self.assertEqual(st[-1], "lost")

    def test_a_carrier_where_the_weak_beacon_was_does_not_keep_the_lock(self):
        # The beacon goes and a carrier sits exactly where it was, at a
        # level inside the hysteresis band: it is held only while it is
        # still the beacon (its traits), so the lock is lost, not kept.
        def swap(d):
            drop("middle beacon")(d)
            d.add_station("carrier", MIDDLE, -64.0)      # ~8 dB: inside the band
        tr, reps, _ = look(-27_000.0, 12, events=[(0.0, drop("lower beacon")), (4.0, swap)])
        late = [r for t, r in reps if t > 6.5]
        self.assertTrue(late)
        self.assertTrue(all(r["state"] != "locked" for r in late), [r["state"] for r in late])
        self.assertTrue(any("single line" in w for r in late for w in r.get("rejected", [])))


class Unsteady(unittest.TestCase):
    """A beacon that will not keep still is named as that (BeaconTracker.
    UNSTEADY_N), not as a station: ohs-box's LNB on 17/10/2026, after a
    few power cycles, came up in a state whose LO jumped hundreds of hertz
    between half-second readings, and for an hour beacon lock said only
    "no 400 Hz symbol line (speech?)"."""

    UNSTEADY = BeaconTracker.UNSTEADY_WHY

    def named(self, reps, after, before=1e9):
        whys = [r["why"] for t, r in reps if after < t < before]
        self.assertTrue(whys)
        return sum(w == self.UNSTEADY for w in whys) / len(whys)

    def test_an_lo_jumping_every_half_second_is_named(self):
        # +-400 Hz every 0.5 s, as the bad period's readings: locked from
        # the start, then lost and found and lost - and said why.
        tr, reps, _ = look(-8_000.0, 30, hops=(400.0, 0.5, 6.0, 1e9))
        self.assertIn("lost", [r["state"] for t, r in reps if t > 10.0])
        self.assertGreater(self.named(reps, 12.0), 0.9)

    def test_an_lo_that_hops_and_sits_between_is_named(self):
        # Still between jumps (300 Hz every 1.5 s): most steps are nothing,
        # and it loses the lock all the same.
        tr, reps, _ = look(-8_000.0, 35, hops=(300.0, 1.5, 6.0, 1e9))
        self.assertGreater(self.named(reps, 20.0), 0.9)

    def test_the_reason_goes_when_the_lo_settles(self):
        tr, reps, _ = look(-8_000.0, 45, hops=(400.0, 0.5, 6.0, 20.0))
        self.assertGreater(self.named(reps, 12.0, 20.0), 0.9)
        self.assertEqual(self.named(reps, 38.0), 0.0)

    def test_a_steady_beacon_is_never_called_unsteady(self):
        # Neither drifting at up to ~22 Hz/s (far faster than a real LNB),
        # nor weak and wandering round the lock's threshold, nor with loud
        # stations either side of it.
        for kw in ({"drift": 300.0}, {"events": WOBBLE, "drift": 60.0},
                   {"extras": [("usb", MIDDLE - 5_300.0, -28.0), ("carrier", MIDDLE + 4_000.0, -30.0)]}):
            with self.subTest(**{k: str(v)[:40] for k, v in kw.items()}):
                tr, reps, _ = look(-27_000.0, 40, **kw)
                self.assertEqual(self.named(reps, 0.0), 0.0)


class NarrowAfterLoss(unittest.TestCase):
    """The narrow search (BeaconTracker.TIGHT_HZ) takes a beacon alone only
    once it has been seen twice in one place, unless the operator has just
    said where it is."""

    def searches_after_a_loss(self, trusted):
        """A steady sim beacon, locked; then the tracker told to search
        again narrowly from 600 Hz off, as after a loss (NARROW_START) or
        the operator's word (NARROW_HAND, `trusted`). The searches' reports,
        up to and including the one that locked."""
        d = SimDevice(sim_cfg(simSeed=3, simRxErrorHz=-8_000.0, simDriftHz=0.0, simDriftSec=120.0))
        d.open()
        d.stations = [st for st in d.stations if st.name != "lower beacon"]   # one beacon alone, as on ohs-box
        an = Analysis(d.geo)
        tr = BeaconTracker(d.geo, "middle", 50_000.0, 0.0)
        out, n, again = [], 0, None
        while n < 40 * d.fs and not (out and out[-1]["state"] == "locked"):
            x = d.read(90_000)
            n += len(x)
            X, st = an.push(x)
            r = tr.process(X, st, d.rx_if, d.lnb_lo, n / d.fs)
            if again is None and tr.state == "locked" and n / d.fs > 5.0:
                again = n
                tr.reset(d.rx_err(n / d.fs) + 600.0, narrow=BeaconTracker.NARROW_HAND if trusted else
                         BeaconTracker.NARROW_START, trusted=trusted)
            elif again is not None and r and "window" in r:
                out.append(r)
        self.assertTrue(out and out[-1]["state"] == "locked", out)
        self.assertTrue(all(r["narrow"] for r in out))
        return out

    def test_after_a_loss_the_narrow_search_waits_for_a_second_sighting(self):
        # It took the beacon at its first sighting until 17/10/2026; on
        # ohs-box that day, with the LO hopping, three of six locks in three
        # minutes were narrow first sightings 1.0-1.4 kHz from where the
        # beacon had been lost, each lost again within two seconds and
        # each moving rxCorr - and the dials - with it (BeaconTracker.
        # CONFIRM_TOL). A steady beacon costs one more second.
        out = self.searches_after_a_loss(trusted=False)
        self.assertEqual([r["state"] for r in out], ["searching", "locked"])
        self.assertTrue(out[0].get("confirming"))

    def test_on_the_operators_word_the_first_sighting_is_enough(self):
        out = self.searches_after_a_loss(trusted=True)
        self.assertEqual([r["state"] for r in out], ["locked"])


class FallBack(unittest.TestCase):
    """When the chosen beacon is not there, or what is there is refused,
    the search takes the other one, at the same floors tracking uses
    (BeaconTracker._acquire_snr) - and says what it heard when it heard
    nothing it could use. Until 13/10/2026 the search asked 18 dB of the
    other beacon (8 more than tracking) and measured the middle beacon's SNR
    against a zeroed noise floor (~140 dB, so its floor never bit), so a
    lower beacon found in the right place every second was never taken."""

    # The simulator's beacons 10 dB down: the lower beacon then reads
    # ~13 dB, the middle beacon ~20; the lower beacon's search SNR is the
    # one that was held to 18 dB.
    DOWN = -10.0

    def test_with_the_middle_beacon_gone_the_lower_one_is_locked_to(self):
        tr, reps, errs = look(-27_000.0, 20, events=[(0.0, drop("middle beacon")), (0.0, beacons_at(self.DOWN))])
        self.assertEqual(tr.state, "locked")
        self.assertEqual({r["used"] for t, r in reps if r["state"] == "locked" and r.get("used")}, {"lower"})
        self.assertLess(np.max(np.abs(errs[-10:])), 5.0)

    def test_with_the_middle_beacon_refused_the_lower_one_is_locked_to(self):
        # A carrier sitting where the middle beacon should be: a candidate,
        # refused (no symbol line), and the lower beacon is used instead.
        def swap(d):
            drop("middle beacon")(d)
            d.add_station("carrier", MIDDLE, -50.0)
        tr, reps, errs = look(-27_000.0, 20, events=[(0.0, swap), (0.0, beacons_at(self.DOWN))])
        self.assertEqual(tr.state, "locked")
        self.assertEqual(tr.used, "lower")
        self.assertLess(np.max(np.abs(errs[-10:])), 5.0)

    def test_the_chosen_beacon_is_preferred_when_both_are_heard(self):
        for choice in ("lower", "middle"):
            tr, reps, _ = look(-27_000.0, 8, choice=choice, events=[(0.0, beacons_at(self.DOWN))])
            self.assertEqual(tr.state, "locked")
            self.assertEqual(reps[-1][1]["used"], choice)

    def test_a_beacon_too_weak_to_lock_to_says_so(self):
        # The middle beacon gone and the lower one heard, but under
        # LOCK_SNR (~5-8 dB here): not locked, and the reason given is the
        # weak beacon, not silence.
        tr, reps, _ = look(-27_000.0, 8, events=[(0.0, drop("middle beacon")), (0.0, beacons_at(-14.0))])
        self.assertNotEqual(tr.state, "locked")
        self.assertIn("lower at", tr.why)
        self.assertIn("too weak", tr.why)

    def test_nothing_on_the_band_is_reported_as_nothing(self):
        # What ohs-box showed on 13/10/2026 when the LNB's signal stopped:
        # noise and the receiver's DC spur. The search must say nothing
        # was heard, not name the spur as a refused "middle at ...".
        tr, reps, _ = look(-27_000.0, 8, events=[(0.0, beacons_at(-80.0))])
        self.assertEqual(tr.state, "searching")
        self.assertEqual(tr.why, "no beacon heard within +-50 kHz")
        self.assertFalse(any(r.get("rejected") for t, r in reps))

    def test_the_receiver_s_own_dc_spur_is_not_named(self):
        # The same, with a spur at the receiver's centre, 3.5 kHz below
        # the middle beacon (RX_CENTRE_DL), as the Pluto showed: refused
        # and not reported. The same carrier anywhere else is named.
        dc = bandplan.BEACONS["middle"]["dl"] - 3_500.0 + 27_000.0      # true downlink at DC, LNB 27 kHz low
        for where, named in ((dc, False), (dc - 10_000.0, True)):
            tr, reps, _ = look(-27_000.0, 6, extras=[("carrier", where, -50.0)], events=[(0.0, beacons_at(-80.0))])
            self.assertEqual(tr.state, "searching")
            self.assertEqual(any(r.get("rejected") for t, r in reps), named, (where, tr.why))


class TxLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _converge(self, mode, vfo, ul_err, seconds, audio=None, drift=200.0, **over):
        r = make_radio(self.tmp, audio_source=audio, mode=mode, vfo=vfo, simUlErrorHz=ul_err, simDriftHz=drift,
                       simDriftSec=300.0, **over)
        r.start()
        try:
            self.assertTrue(wait_rx_lock(r))
            run_sim(r, 1.5)                 # learn the baseline unkeyed
            r.ptt(True)
            run_sim(r, seconds)
            s = r.state()
            self.assertTrue(s["keyed"])
            return s, r.dev
        finally:
            r.stop()

    def test_an_over_logs_what_came_back_down(self):
        # The over's own-signal result, after its start and end lines: a
        # log alone then says whether the over reached the satellite.
        r = make_radio(self.tmp, mode="cw", vfo=10_489_520_000.0, simUlErrorHz=300.0, simDriftHz=0.0)
        r.start()
        try:
            self.assertTrue(wait_rx_lock(r))
            run_sim(r, 1.5)
            with self.assertLogs("ohsnb.radio", "INFO") as cm:
                r.ptt(True)
                run_sim(r, 4)
                r.ptt(False)
                run_sim(r, 1, until=lambda: not r.state()["keyed"])
            text = "\n".join(cm.output)
        finally:
            r.stop()
        self.assertRegex(text, r"over start: cw \(tune\); sim at \d+ Hz uplink, TX gain [+-][\d.]+ dB, "
                               r"txCorr [+-]\d+ Hz")
        self.assertRegex(text, r"over end: cw after [\d.]+ s on air, ended normal")
        self.assertRegex(text, r"own signal: found in \d+ of \d+ measurements, vs beacon max [+-][\d.]+ dB, "
                               r"median [+-][\d.]+ dB, frequency error median [+-]\d+ Hz \(\w+\)")

    def test_cw_carrier_converges_from_3_khz(self):
        s, dev = self._converge("cw", 10_489_520_000.0, 3000.0, 6)
        self.assertLess(abs(s["txCorr"] + 3000.0), 10.0)
        self.assertEqual(s["txLockState"], "locked")
        self.assertAlmostEqual(s["ownDl"], s["txDial"], delta=10.0)

    def test_found_off_the_dial_is_landed_not_searching(self):
        # 0.1.3: "SEARCHING -2.900 kHz" on the badge while the status strip
        # already showed txCorr +2900 - the engine called a found and
        # corrected signal "searching" until the next measurement agreed.
        r = make_radio(self.tmp, mode="cw", vfo=10_489_520_000.0, simUlErrorHz=3000.0, simDriftHz=0.0)
        r.start()
        try:
            self.assertTrue(wait_rx_lock(r))
            run_sim(r, 1.5)
            r.ptt(True)
            run_sim(r, 0.05)
            self.assertEqual(r.state()["txLockState"], "searching")      # nothing measured this over yet
            seen = []
            run_sim(r, 8, until=lambda: (seen.append(dict(r.state())) or seen[-1]["txLockState"] == "locked"))
            states = [s["txLockState"] for s in seen]
            landed = next(s for s in seen if s["txLockState"] == "landed")
            self.assertAlmostEqual(landed["txErr"], 3000.0, delta=10.0)          # where it came down
            self.assertAlmostEqual(landed["txCorr"], -3000.0, delta=10.0)        # and already corrected for
            self.assertEqual(states[-1], "locked")
            self.assertNotIn("searching", states[states.index("landed"):])      # found is never "searching" again
        finally:
            r.stop()

    def test_ssb_audio_converges_from_3_khz(self):
        s, _ = self._converge("usb", 10_489_700_000.0, 3000.0, 8, audio=noise_audio())
        self.assertLess(abs(s["txCorr"] + 3000.0), 10.0)

    def test_wide_acquisition_of_a_pluto_sized_error(self):
        # -47 kHz: a Pluto ~20 ppm out at 2.4 GHz.
        s, _ = self._converge("usb", 10_489_800_000.0, -47_000.0, 8, audio=noise_audio())
        self.assertLess(abs(s["txCorr"] - 47_000.0), 10.0)

    def test_gps_locked_lnb_predicts_tx_correction(self):
        # The sim's SDR reference makes rxCorr; with a GPS LNB the same ppm
        # error appears at the uplink, scaled by uplink / receiver IF.
        r = make_radio(self.tmp, lnbGpsLocked=True, simRxErrorHz=-1500.0)
        r.start()
        try:
            self.assertTrue(wait_rx_lock(r))
            run_sim(r, 1.0)
            s = r.state()
            f_rx = s["rxDial"] - r.lnb_lo + s["rxCorr"]
            want = s["rxCorr"] * bandplan.ul(s["txDial"]) / f_rx
            self.assertAlmostEqual(s["txCorr"], want, delta=abs(want) * 0.01)
            self.assertTrue(s["txCorrTrusted"])
        finally:
            r.stop()


if __name__ == "__main__":
    unittest.main()
