"""A broadcast station's own receiver gain (ohsradio/bcastgain.py).

Measured on ohs-box (store Radio 0.1.22-beta.6): DAB on a local 48 dB
multiplex glitched because it inherited the operator's manual rxGain, set
for weak amateur signals, and overloaded the RSPdx. Here, on the RSPdx-
shaped simulator with an overload model (a device that reports overload
whenever its gain is above a threshold, as the SDRplay API does):

- **The policy itself,** on a clock of its own, against the ohs-box
  sweep (24/10/2026): it starts at LNA state 6 (rxGain 45 under
  SoapySDRPlay3's sense, where less gain is a *higher* number); with DAB
  it moves only on FIB errors - a flickering overload flag on clean FIBs
  moves nothing, errors with overload back off until they stop, errors
  without it climb back, and a step that makes errors worse (the weak
  blocks' cliff at 50) is undone and never tried again; with only the
  overload report (wide FM) it is debounced and creeps back slowly; a
  radio with no overload report holds a fixed default.
- **In the radio:** a DAB session settles below the overload threshold
  and says so in `broadcastGain`; wide FM the same; the operator's
  `rxGain` setting never moves; the device gets the operator's exact gain
  back on every way a station ends - the session stopped, the radio
  stopped (and started again), a mode change out of wide FM, DAB started
  over background sessions it dropped and then stopped; the other modes
  and a background decoder never see a gain but the operator's.
- **The S-meter:** reads the gain applied, says why it is uncalibrated
  when the broadcast gain moved a stage it cannot correct, and refuses a
  calibration while the station sets the gain, leaving the stored table
  untouched.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import time
import unittest
from unittest import mock

from ohscore import sdr, smeter_cal
from ohsradio import bcastgain
from ohsradio.bcastgain import Ladder, Policy
from ohsradio.radio import Radio

from listen_helpers import ListeningSim, TapAudio

DAB_CENTRE = 222_064_000.0          # 11D
HOME = 145_500_000.0
FM_STATION = 97_700_000.0


class Clock:
    """A Policy driven by hand: `run(seconds, overloaded, fib_bad)` ticks it
    ten times a second, as Radio's supervisor does. `overloaded(gain, i)`
    says whether the device reports a new overload at tick `i`;
    `fib_bad(gain)` is the share of FIBs failing at that gain (None: no
    FIBs, as wide FM), 125 a second as DAB sends them. `seen` is every
    gain the policy applied."""

    def __init__(self, policy):
        self.p, self.t, self.i = policy, 1000.0, 0
        self.ok = self.bad = 0.0
        self.seen = []

    def run(self, seconds, overloaded, fib_bad=lambda g: None):
        for _ in range(int(round(seconds * 10))):
            self.t += 0.1
            self.i += 1
            frac = fib_bad(self.p.gain)
            fibs = None
            if frac is not None:
                self.bad += 12.5 * frac
                self.ok += 12.5 * (1 - frac)
                fibs = (int(self.ok), int(self.bad))
            self.p.tick(self.t, overloaded(self.p.gain, self.i), fibs)
            self.seen.append(self.p.gain)


def ohs_box(g):
    """The FIB errors of the ohs-box sweep's blocks (24/10/2026), by rxGain
    under SoapySDRPlay3's sense: clean from 45 (LNA state 6) to 49, the
    weak blocks' cliff from 50 (LNA state 11)."""
    return 0.0 if g < 50 else 0.5


def flicker(g, i):
    """The SDRplay overload flag as the sweep saw it at 45 on clean blocks:
    up every other look."""
    return i % 2 == 0


class ThePolicy(unittest.TestCase):
    def soapy(self, operator=40.0):
        p = Policy()
        c = Clock(p)
        p.begin(("dab", "s1"), c.t, "soapysdrplay3", [0, 27], operator, adaptive=True)
        return p, c

    def test_ohs_box_starts_at_lna_state_6(self):
        p, _c = self.soapy()
        self.assertEqual(p.wanted, ("manual", 45.0))

    def test_a_flickering_overload_moves_nothing_while_the_fibs_are_clean(self):
        p, c = self.soapy()
        c.run(120, flicker, ohs_box)
        self.assertEqual(set(c.seen), {45.0})
        self.assertEqual((p.view()["signal"], p.view()["fibBad"], p.view()["state"]), ("fibs", 0.0, "settled"))

    def test_errors_with_overload_back_off_until_they_stop(self):
        # The local multiplex: overloaded, with errors, up to 46.
        p, c = self.soapy()
        c.run(30, lambda g, i: g <= 46.0, lambda g: 0.12 if g <= 46.0 else ohs_box(g))
        self.assertEqual(p.gain, 47.0)
        self.assertLess(max(c.seen), 50.0)
        self.assertEqual(p.view()["state"], "settled")

    def test_never_past_the_weak_signal_cliff(self):
        # Errors with the flag up everywhere, worse from 48 (the weak side):
        # tried once, undone, and barred.
        p, c = self.soapy()
        c.run(60, lambda g, i: True, lambda g: 0.05 if g <= 47.0 else 0.4)
        self.assertEqual((p.gain, p.view()["floorDb"]), (47.0, 48.0))
        self.assertLessEqual(max(c.seen), 48.0)
        self.assertEqual(c.seen[-200:], [47.0] * 200)
        self.assertTrue(p.view()["atLimit"])

    def test_weak_signal_errors_bring_the_gain_back_up(self):
        # Errors and no overload: too little gain, so more - as far as the
        # operator's own 40, never past it.
        p, c = self.soapy()
        c.run(60, lambda g, i: False, lambda g: 0.1 if g >= 43.0 else 0.0)
        self.assertEqual(p.gain, 42.0)
        p2, c2 = self.soapy()
        c2.run(60, lambda g, i: False, lambda g: 0.1)
        self.assertEqual(min(c2.seen), 40.0)

    def test_overload_alone_is_debounced(self):
        p = Policy()
        c = Clock(p)
        p.begin(("wfm",), c.t, "db", None, 40.0, adaptive=True)
        c.run(60, lambda g, i: i % 25 == 0)                 # a flicker every 2.5 s: never three windows running
        self.assertEqual(p.gain, 30.0)
        c.run(4, lambda g, i: g > 22.0)
        self.assertEqual(p.gain, 27.0)                       # three running: one step

    def test_overload_alone_creeps_back_but_not_into_what_overloaded(self):
        p = Policy()
        c = Clock(p)
        p.begin(("wfm",), c.t, "db", None, 40.0, adaptive=True)
        c.run(20, lambda g, i: g > 25.0)
        self.assertEqual(p.gain, 24.0)
        c.run(bcastgain.MEMORY_S - 40, lambda g, i: False)
        self.assertEqual(p.gain, 24.0)                       # 27 overloaded within MEMORY_S
        c.run(bcastgain.CREEP_S * 10, lambda g, i: False)
        self.assertEqual(p.gain, 30.0)                       # then back to the start, never past it

    def test_an_operator_already_below_the_default_keeps_their_gain(self):
        p = Policy()
        p.begin(("wfm",), 0.0, "db", None, 18.0, adaptive=True)
        self.assertEqual(p.gain, 18.0)

    def test_a_radio_with_no_overload_report_holds_the_default_for_wide_fm(self):
        p = Policy()
        c = Clock(p)
        p.begin(("wfm",), c.t, "db", None, 50.0, adaptive=False)
        c.run(60, lambda g, i: True)
        self.assertEqual((p.gain, p.view()["state"], p.view()["adaptive"]), (30.0, "fixed", False))

    def test_the_ladders_ends(self):
        self.assertIsNone(Ladder("db").less(0.0))
        self.assertIsNone(Ladder("sdrplay").less(20.0))        # gRdB 59, the most SDRplay reduces
        self.assertEqual(Ladder("sdrplay").start(40.0), 30.0)
        soapy = Ladder("soapysdrplay3", [0, 9])                # an RSP1A's nine LNA states
        self.assertIsNone(soapy.less(48.0))
        self.assertEqual(soapy.start(47.0), 47.0)              # already less gain than the default


class OverloadingSim(ListeningSim):
    """The RSPdx-shaped simulator reporting overload, as SDRplay's API does,
    while its gain is above `over_above` (or, with model "soapysdrplay3",
    whose rxGain is a reduction, below it). `gain` is what the device has
    now: the configuration's until the engine sets another."""

    def __init__(self, cfg, fs=2_400_000.0, stations=(), receive_only=True, over_above=24.0, model="db",
                 reports=True):
        self.gains = []
        super().__init__(cfg, fs, stations, receive_only)
        self.over_above, self.model, self.reports = float(over_above), model, reports
        self.gain = (cfg.get("rxGainMode"), float(cfg.get("rxGain", 40.0)))
        self.gains = []                      # the set-up's own call is the configuration's, not the engine's
        self.overloads = 0

    def open(self):
        # As a real radio does: opened with the gain its configuration gives.
        super().open()
        self.gain = (self.cfg.get("rxGainMode"), float(self.cfg.get("rxGain", 40.0)))

    def set_rx_gain(self, mode, db):
        super().set_rx_gain(mode, db)
        self.gain = (mode, float(db))
        self.gains.append(self.gain)

    def gain_sense(self):
        return {"gainIsReduction": self.model == "soapysdrplay3", "gainModel": self.model, "rfgrRange": [0, 27]}

    def overloaded(self):
        g = self.gain[1]
        return g < self.over_above if self.model == "soapysdrplay3" else g > self.over_above

    def status(self):
        st = super().status()
        if self.reports:
            over = self.overloaded()
            self.overloads += int(over)
            st.update(overloaded=over, overloads=self.overloads)
        return st


def wait(radio, cond, timeout=40.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        radio.heartbeat()
        if cond():
            return True
        time.sleep(0.02)
    return False


OPERATOR = ("manual", 40.0)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class InTheRadio(unittest.TestCase):
    def radio(self, mode="fm", vfo=HOME, **dev_kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # make_listener's set-up (listen_helpers), with the overloading device.
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": vfo, "mode": mode,
               "rxGainMode": "manual", "rxGain": 40.0}
        dev = OverloadingSim(dict(cfg), **dev_kw)
        r = Radio(cfg, persist=False, data_dir=tmp.name, audio=TapAudio(), device=dev)
        self.addCleanup(r.stop)
        # A short hold, so "settled" comes in a second rather than five.
        p = mock.patch.object(bcastgain, "HOLD_S", 1.0)
        p.start()
        self.addCleanup(p.stop)
        r.start()
        return r, dev

    def settled(self, r):
        return wait(r, lambda: (r.state()["broadcastGain"] or {}).get("state") == "settled")

    def test_dab_settles_below_the_overload_and_says_so(self):
        r, dev = self.radio()
        sess = r.decoders.start("dab", DAB_CENTRE, {})
        self.assertTrue(self.settled(r), r.state()["broadcastGain"])
        bg = r.state()["broadcastGain"]
        self.assertLessEqual(dev.gain[1], 24.0)
        self.assertFalse(dev.overloaded())
        self.assertEqual((bg["auto"], bg["db"], bg["operatorDb"], bg["gainModel"], bg["adaptive"]),
                         (True, dev.gain[1], 40.0, "db", True))
        self.assertGreater(bg["backoffs"], 0)
        self.assertEqual(r.state()["rxGain"], 40.0)          # the operator's setting never moved
        self.assertEqual(r.cfg["rxGain"], 40.0)
        self.assertTrue(r.decoders.stop(sess["id"]))
        self.assertTrue(wait(r, lambda: dev.gain == OPERATOR), dev.gains[-5:])
        self.assertEqual(r.state()["broadcastGain"], {})

    def test_the_radio_stopping_leaves_the_operators_gain(self):
        r, dev = self.radio()
        r.decoders.start("dab", DAB_CENTRE, {})
        self.assertTrue(self.settled(r))
        r.stop()
        self.assertEqual((r.state()["broadcastGain"], r.state()["rxGain"], r.cfg["rxGain"]), ({}, 40.0, 40.0))
        dev.gains.clear()
        r.start()                            # opened again from the configuration: the operator's gain
        self.assertTrue(wait(r, lambda: r.running))
        time.sleep(0.5)
        self.assertEqual(r.state()["broadcastGain"], {})
        self.assertEqual(dev.gain, OPERATOR)
        self.assertEqual([g for g in dev.gains if g != OPERATOR], [])

    def test_wide_fm_has_it_and_a_mode_change_gives_it_back(self):
        r, dev = self.radio(mode="wfm", vfo=FM_STATION)
        self.assertTrue(self.settled(r))
        self.assertLessEqual(dev.gain[1], 24.0)
        r.set(mode="fm")
        self.assertTrue(wait(r, lambda: dev.gain == OPERATOR))
        self.assertEqual(r.state()["broadcastGain"], {})

    def test_dab_over_dropped_sessions_then_stopped_gives_the_operators_gain(self):
        r, dev = self.radio()
        r.decoders.start("rtty", 145_400_000.0, {})
        sess = r.decoders.start("dab", DAB_CENTRE, {}, drop_sessions=True)
        self.assertTrue(self.settled(r))
        self.assertEqual(r.decoders.background(), [])
        r.decoders.stop(sess["id"])
        self.assertTrue(wait(r, lambda: dev.gain == OPERATOR))

    def test_other_modes_and_background_decoders_keep_the_operators_gain(self):
        r, dev = self.radio()
        r.decoders.start("rtty", 145_400_000.0, {})
        for mode in ("fm", "usb", "cw", "am"):
            r.set(mode=mode)
            time.sleep(0.3)
        self.assertEqual(r.state()["broadcastGain"], {})
        self.assertEqual([g for g in dev.gains if g != OPERATOR], [])
        self.assertTrue(dev.overloaded())                    # overloading, and still nothing changed: not broadcast

    def test_a_radio_that_reports_no_overload_gets_the_fixed_default(self):
        r, dev = self.radio(reports=False)
        sess = r.decoders.start("dab", DAB_CENTRE, {})
        self.assertTrue(wait(r, lambda: (r.state()["broadcastGain"] or {}).get("adaptive") is False))
        self.assertTrue(wait(r, lambda: dev.gain == ("manual", 30.0)))
        r.decoders.stop(sess["id"])
        self.assertTrue(wait(r, lambda: dev.gain == OPERATOR))

    def test_under_the_radios_own_agc_nothing_changes(self):
        r, dev = self.radio()
        r.set(rxGainMode="slow_attack")
        r.decoders.start("dab", DAB_CENTRE, {})
        self.assertTrue(wait(r, lambda: (r.state()["broadcastGain"] or {}).get("why") == "agc"))
        self.assertEqual(r.state()["broadcastGain"]["auto"], False)
        self.assertNotIn(("manual", 30.0), dev.gains)

    def test_soapysdrplay3_settles_with_fewer_lna_states_of_gain(self):
        r, dev = self.radio(model="soapysdrplay3", over_above=47.0)
        r.decoders.start("dab", DAB_CENTRE, {})
        self.assertTrue(wait(r, lambda: dev.gain[1] >= 47.0))
        self.assertTrue(self.settled(r))
        self.assertEqual(r.state()["broadcastGain"]["gainModel"], "soapysdrplay3")

    def test_dab_with_clean_fibs_ignores_the_overload_flag(self):
        # ohs-box at 45: the flag up on blocks whose FIBs are all clean.
        r, dev = self.radio(model="soapysdrplay3", over_above=99.0)
        fibs = {"ok": 0}

        def stats(sid):
            fibs["ok"] += 13
            return {"fibsOk": fibs["ok"], "fibsBad": 0}
        with mock.patch.object(r.decoders, "held_stats", stats):
            r.decoders.start("dab", DAB_CENTRE, {})
            self.assertTrue(self.settled(r))
            time.sleep(3)
        self.assertGreater(dev.overloads, 20)
        self.assertEqual(set(dev.gains), {("manual", 45.0)})
        self.assertEqual(r.state()["broadcastGain"]["signal"], "fibs")


class TheSMeter(unittest.TestCase):
    """smeter_cal reads the applied gain (the `broadcastGain` status)."""

    def st(self, model="db", bg=None, rx_gain=40.0):
        return {"device": "pluto", "plutoUri": "ip:pluto", "band": "2m", "rxGainMode": "manual", "rxGain": rx_gain,
                "deviceStatus": {"gainModel": model, "rfgrRange": [0, 27]}, "broadcastGain": bg or {}}

    def test_a_plain_gain_is_corrected_for_the_broadcast_one(self):
        table = smeter_cal.calibrate("", self.st(), -60.0, -93.0)
        now = smeter_cal.effective(table, self.st(bg={"auto": True, "db": 28.0}))
        self.assertTrue(now.ok)
        self.assertAlmostEqual(now.offset, (-93.0 + 60.0) + 12.0)    # 12 dB less gain: 12 dB more to add

    def test_an_lna_step_says_uncalibrated_for_the_station_and_keeps_the_table(self):
        table = smeter_cal.calibrate("", self.st("soapysdrplay3"), -60.0, -93.0)
        stored = smeter_cal.format_cal(table)
        now = smeter_cal.effective(stored, self.st("soapysdrplay3", {"auto": True, "db": 43.0}))
        self.assertEqual((now.ok, now.why_code), (False, "broadcast_gain"))
        with self.assertRaises(ValueError):
            smeter_cal.calibrate(stored, self.st("soapysdrplay3", {"auto": True, "db": 43.0}), -50.0, -80.0)
        self.assertTrue(smeter_cal.effective(stored, self.st("soapysdrplay3")).ok)   # whole again after

    def test_the_operators_gain_stands_when_the_policy_is_idle(self):
        st = self.st(bg={"auto": False, "db": None, "why": "agc"})
        self.assertEqual(smeter_cal.known_gain(st), 40.0)


if __name__ == "__main__":
    unittest.main()
