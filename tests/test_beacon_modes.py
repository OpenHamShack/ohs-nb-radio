"""Beacon lock's modes (Auto, Hold, Manual), click-to-lock, and what must
keep working whichever is in charge of rxCorr - end to end on the
simulated transponder."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim, sim_cfg, sim_seconds, wait_rx_lock
from ohsnb import bandplan, config
from ohsnb.devices.sim import SimDevice
from ohsnb.radio import RX_CENTRE_DL, Radio

MIDDLE = bandplan.BEACONS["middle"]["ref"]
LOWER = bandplan.BEACONS["lower"]["dl"]


class DecoySim(SimDevice):
    """The band as it must look for click-to-lock to matter: a second
    BPSK beacon, 6 dB louder than the real one, 20 kHz below it, and no
    lower beacon to contradict it - so beacon lock's own search, which
    takes the strongest beacon-like signal, chooses the copy."""

    def open(self):
        super().open()
        self.stations = [s for s in self.stations if s.name != "lower beacon"]
        self.add_station("bpsk", MIDDLE - 20_000.0, -34.0)


def tones(radio, zoom, seconds=1.0):
    """Where the zoom scope shows the lower beacon's two F1A tones (dial Hz),
    from the average of its last few lines."""
    zoom.drain()
    got = run_sim(radio, seconds, [zoom])["zoom"]
    _, start, bin_hz, _ = got[-1]
    avg = np.mean([it[3] for it in got[-5:]], axis=0)
    f = start + bin_hz * np.arange(len(avg))
    out = []
    for lo, hi in ((f[0], (f[0] + f[-1]) / 2), ((f[0] + f[-1]) / 2, f[-1])):
        sel = (f >= lo) & (f < hi)
        out.append(float(f[sel][np.argmax(avg[sel])]))
    return out, bin_hz


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def radio(self, start=True, **over):
        r = make_radio(self.tmp, **over)
        self.radios.append(r)
        if start:
            r.start()
        return r

    def run_until(self, r, cond, seconds=15.0):
        run_sim(r, seconds, until=cond)
        return cond()


class ClickToLock(Case):
    def test_the_clicked_frequency_becomes_the_beacon_s_reference(self):
        # Without a look (snap off, or the radio stopped) the click itself
        # is the beacon: rxCorr moves by exactly the click's distance from
        # where the beacon's marker stands.
        r = self.radio(start=False, rxCorr=1_000.0)
        r.beacon_here("middle", MIDDLE + 250.0, snap=False)
        self.assertAlmostEqual(r.state()["rxCorr"], 1_250.0, delta=0.05)
        # An F1A beacon is marked at its nominal (lower) tone.
        r.beacon_here("lower", LOWER - 400.0, snap=False)
        self.assertAlmostEqual(r.state()["rxCorr"], 850.0, delta=0.05)
        self.assertTrue(r.state()["rxCorrHand"])
        with self.assertRaises(ValueError):
            r.beacon_here("multimedia", MIDDLE)

    def test_a_click_wins_over_a_louder_decoy(self):
        # LNB 45 kHz out. Beacon lock's own search locks to the copy (the
        # strongest beacon-like signal, nothing to contradict it); the
        # operator clicks roughly - 150 Hz off - on the real one.
        r = self.radio(device=DecoySim, simRxErrorHz=45_000.0, beaconSearchHz=50_000.0)
        toasts = r.subscribe("toast", 50)
        self.assertTrue(wait_rx_lock(r))
        run_sim(r, 1.0)
        self.assertAlmostEqual(r.state()["rxCorr"], 25_000.0, delta=5.0)
        real_on_screen = MIDDLE + 45_000.0 - r.state()["rxCorr"]
        r.beacon_here("middle", real_on_screen + 150.0)
        ok = self.run_until(r, lambda: r.state()["rxLock"] == "locked" and abs(r.state()["rxCorr"] - 45_000.0) < 5)
        self.assertTrue(ok, r.state()["rxCorr"])
        run_sim(r, 8.0)                     # and it stays there
        s = r.state()
        self.assertEqual(s["rxLock"], "locked")
        self.assertLess(abs(s["rxCorr"] - r.dev.rx_err(sim_seconds(r))), 5.0)
        self.assertTrue(s["rxCorrHand"])
        said = [t["text"] for t in toasts.drain()]
        self.assertTrue(any(t.startswith("Middle beacon set where you clicked (snapped") for t in said), said)

    def test_a_click_snaps_to_the_lower_beacon_s_tone_pair(self):
        # Hold: the click sets the correction and nothing tracks after it.
        # A click between the two tones lands on their midpoint.
        r = self.radio(beaconMode="hold", simRxErrorHz=3_000.0)
        run_sim(r, 1.0)
        r.beacon_here("lower", LOWER + 3_000.0 + 250.0)
        self.assertTrue(self.run_until(r, lambda: r.state()["rxCorrHand"], 5.0))
        s = r.state()
        self.assertAlmostEqual(s["rxCorr"], 3_000.0, delta=3.0)
        self.assertEqual(s["rxLock"], "hold")


class Modes(Case):
    def test_hold_freezes_the_correction_while_the_lnb_drifts(self):
        # +-300 Hz over 60 s: up to ~45 Hz/s, twice the 22 Hz/s the tracker
        # was tuned against and far beyond a real LNB. It was +-600 Hz (up to
        # ~90 Hz/s) until 07/10/2026: past the tracker's envelope, so that
        # where the wander was when Hold ended decided the result - from
        # the fastest part, a narrow re-acquisition is ~100 Hz stale by its
        # first tracking look, beyond MAX_TRACK_ERR, and the lock is lost.
        # The development PC's heartbeats happened to end Hold early in the
        # cycle; an M4 Mac, running the unpaced simulator 2.7x faster, ended
        # it later, and failed this test two runs in three.
        r = self.radio(simDriftHz=300.0, simDriftSec=60.0)
        self.assertTrue(wait_rx_lock(r))
        reports = r.subscribe("lock", 500)
        r.set(beaconMode="hold")
        run_sim(r, 0.5)
        held = r.state()["rxCorr"]
        t0 = sim_seconds(r)
        # The wander is a sum of sines, so how far it moves in a fixed time
        # depends on where in its cycle the hold began - which depends on
        # how long the lock took, and so on the machine's load. Run until it
        # has moved, instead of for a fixed 10 s that can land near a turn.
        run_sim(r, 40.0, until=lambda: abs(r.dev.rx_err(sim_seconds(r)) - r.dev.rx_err(t0)) > 80.0)
        s = r.state()
        drift = r.dev.rx_err(sim_seconds(r)) - r.dev.rx_err(t0)
        self.assertGreater(abs(drift), 50.0)               # the LNB moved...
        self.assertEqual(s["rxCorr"], held)                # ...and the correction did not
        self.assertEqual(s["rxLock"], "hold")
        self.assertFalse(s["rxCorrHand"])                  # still beacon lock's own value
        # The beacon goes on being measured: its error is the drift - the
        # drift at the moment of the measurement, which is the report's
        # stream time. Not at sim_seconds() now: the simulator runs unpaced,
        # and between a report and this line it ran on 0.5 s of signal on
        # the development PC and 1.2 s on an M4 Mac, with the LNB moving up
        # to ~90 Hz/s - which failed this check on the Mac two runs in three.
        held_reports = [it for it in reports.drain() if it.get("state") == "held"]
        last = held_reports[-1]
        self.assertAlmostEqual(last["err"], r.dev.rx_err(last["stream"]) - held, delta=40.0)
        self.assertGreater(s["beaconLevel"], -100.0)
        # Back to Auto: from the held correction, narrowly first.
        lock = r.subscribe("lock", 200)
        r.set(beaconMode="auto")
        self.assertTrue(self.run_until(r, lambda: r.state()["rxLock"] == "locked", 10.0))
        acq = [it for it in lock.drain() if it.get("acquired") is not None]
        self.assertTrue(acq and acq[0]["window"] == 2_000.0 and acq[0]["narrow"])
        lock.drain()
        run_sim(r, 3.0)
        # Tracking, not locked still: the LNB is still wandering (the hold
        # above waited for it to move, so it may be at its fastest), and the
        # tracker follows it a few hertz behind - measured, as above, at
        # the stream time of its own last report.
        last = [it for it in lock.drain() if "stream" in it][-1]
        self.assertLess(abs(last["rxCorr"] - r.dev.rx_err(last["stream"])), 25.0)

    def test_manual_nudges_move_rxcorr_and_the_displayed_frequencies(self):
        r = self.radio(simRxErrorHz=17_000.0, zoomSpanHz=2000.0, zoomBins=1024, vfo=LOWER + 200.0, zoomPan=0.0)
        zoom = r.subscribe("zoom", 50)
        self.assertTrue(wait_rx_lock(r))
        r.set(beaconMode="manual")
        run_sim(r, 1.0)
        before, zb = tones(r, zoom)
        c0 = r.state()["rxCorr"]
        r.set(rxCorr=c0 + 100.0)
        run_sim(r, 1.5)
        after, _ = tones(r, zoom)
        self.assertEqual(r.state()["rxCorr"], c0 + 100.0)
        self.assertEqual(r.state()["rxLock"], "manual")
        for a, b in zip(before, after):
            self.assertAlmostEqual(b - a, -100.0, delta=zb + 2.0)
        # The measured error says how far the beacon now is from where
        # it is held: what the operator nudges back by.
        self.assertAlmostEqual(r.state()["rxErr"], -100.0, delta=10.0)

    def test_a_hand_set_correction_recentres_the_receiver_and_the_scopes_follow(self):
        r = self.radio(simRxErrorHz=17_000.0, zoomSpanHz=2000.0, zoomBins=1024, vfo=LOWER - 3_000.0 + 200.0)
        zoom = r.subscribe("zoom", 50)
        self.assertTrue(wait_rx_lock(r))
        r.set(beaconMode="manual")
        c0 = r.state()["rxCorr"]
        r.set(rxCorr=c0 + 3_000.0)
        run_sim(r, 1.5)
        want_if = RX_CENTRE_DL - r.lnb_lo + c0 + 3_000.0
        self.assertAlmostEqual(r.rx_if, want_if, delta=0.01)
        self.assertAlmostEqual(r.dev.rx_if, want_if, delta=0.01)
        (lo, hi), zb = tones(r, zoom)
        self.assertAlmostEqual(lo, LOWER - 3_000.0, delta=zb + 3.0)
        self.assertAlmostEqual(hi, LOWER - 2_600.0, delta=zb + 3.0)

    def test_the_gps_prediction_never_uses_a_hand_set_correction(self):
        r = self.radio(lnbGpsLocked=True, simRxErrorHz=-1_500.0, beaconMode="manual")
        r.set(rxCorr=-1_490.0)
        run_sim(r, 3.0)
        self.assertFalse(r.state()["txCorrTrusted"])
        # Auto from there: the lock it finds narrowly is still the hand's.
        r.set(beaconMode="auto")
        self.assertTrue(wait_rx_lock(r))
        run_sim(r, 2.0)
        s = r.state()
        self.assertTrue(s["rxCorrHand"])
        self.assertFalse(s["txCorrTrusted"])
        self.assertEqual(s["txCorr"], 0.0)

    def test_tx_lock_and_the_level_guard_work_in_hold_and_manual(self):
        # The sim's own signal equals the beacon at -20 dB; at -5 dB it is
        # 15 dB over. Transmit error 3 kHz.
        for mode in ("hold", "manual"):
            with self.subTest(mode=mode):
                r = self.radio(mode="cw", vfo=10_489_520_000.0, txGain=-5.0, txGainCeiling=0.0, levelMarginDb=6.0,
                               simUlErrorHz=3_000.0)
                self.assertTrue(wait_rx_lock(r))
                r.set(beaconMode=mode)
                run_sim(r, 1.5)
                r.ptt(True)
                run_sim(r, 8.0)
                s = r.state()
                self.assertTrue(s["keyed"])
                self.assertLess(abs(s["txCorr"] + 3_000.0), 10.0)
                self.assertLess(s["txGain"], -20.0)
                self.assertLess(s["vsBeacon"], -4.0)
                r.ptt(False)


class NoMiddleSim(SimDevice):
    """The band with the middle beacon off the air and the lower one 10 dB
    under the simulator's level (~13 dB, a few over LOCK_SNR)."""

    def open(self):
        super().open()
        self.stations = [s for s in self.stations if s.name != "middle beacon"]
        for s in self.stations:
            if s.name == "lower beacon":
                s.amp *= 10 ** (-10.0 / 20)


class ChosenBeacon(Case):
    """The `beacon` setting, live, and the fall-back to the other beacon
    when the chosen one is not on the air - through the radio, as the
    operator's /api/set reaches it."""

    def test_the_beacon_setting_takes_effect_while_locked(self):
        r = self.radio()
        self.assertTrue(wait_rx_lock(r))
        self.assertTrue(self.run_until(r, lambda: r.state()["beaconUsed"] == "middle", 3.0))
        r.set(beacon="lower")
        self.assertTrue(self.run_until(r, lambda: r.state()["beaconUsed"] == "lower", 5.0))
        self.assertEqual(r.state()["rxLock"], "locked")
        r.set(beacon="middle")
        self.assertTrue(self.run_until(r, lambda: r.state()["beaconUsed"] == "middle", 5.0))
        self.assertEqual(r.state()["rxLock"], "locked")
        self.assertLess(abs(r.state()["rxCorr"] - r.dev.rx_err(sim_seconds(r))), 25.0)

    def test_with_the_middle_beacon_off_the_air_it_locks_to_the_lower(self):
        r = self.radio(device=NoMiddleSim, simRxErrorHz=-27_000.0)
        self.assertEqual(r.state()["beacon"], "middle")
        self.assertTrue(wait_rx_lock(r, 20.0))
        self.assertTrue(self.run_until(r, lambda: r.state()["beaconUsed"] == "lower", 3.0))
        self.assertLess(abs(r.state()["rxCorr"] - r.dev.rx_err(sim_seconds(r))), 25.0)


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conf = Path(self.tmp.name) / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_beacon_lock_on_becomes_auto_and_off_becomes_hold(self):
        for old, want in ((True, "auto"), (False, "hold")):
            self.conf.write_text(json.dumps({"beaconLock": old, "rxCorr": -27454.0}))
            cfg = config.load(self.conf)
            self.assertEqual(cfg["beaconMode"], want)
            self.assertEqual(cfg["rxCorr"], -27454.0)
            config.save(cfg, self.conf)
            saved = json.loads(self.conf.read_text())
            self.assertNotIn("beaconLock", saved)
            self.assertEqual(saved["beaconMode"], want)

    def test_a_file_with_both_keeps_the_new_one(self):
        self.conf.write_text(json.dumps({"beaconLock": False, "beaconMode": "manual"}))
        self.assertEqual(config.load(self.conf)["beaconMode"], "manual")

    def test_a_dict_handed_to_the_engine_is_translated_too(self):
        cfg = sim_cfg()
        cfg.pop("beaconMode")
        cfg["beaconLock"] = False
        r = Radio(cfg, persist=False, data_dir=self.tmp.name)
        self.assertEqual(r.state()["beaconMode"], "hold")


if __name__ == "__main__":
    unittest.main()
