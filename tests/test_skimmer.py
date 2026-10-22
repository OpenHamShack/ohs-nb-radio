import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The band skimmer (ohsnb/dsp/skim.py, ohsnb/skimmer.py): signals on the
simulated band come out of it found and named - a voice with its dial
measured by auto-tune, a carrier, a steady data signal, the beacons, a
KG-STV-shaped signal where KG-STV is - and its CPU budget holds it to fewer
looks rather than more CPU. Then the engine's half: the "skim" feed and the
skim* keys while the radio runs, and the calls an FT8 decoder heard put on
the FT8 window's entry.

The simulator's band is built here station by station (simSignals off), so
every signal's true frequency is known. Its real-recording behaviour is
measured by tools/skimmer_eval.py against the labelled corpora (the commit
messages and docs/PERF.md have the figures)."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim, sim_cfg
from ohscore.dsp.bank import Analysis, Source
from ohsnb import bandplan
from ohsnb.devices.sim import FT8Activity, SimDevice
from ohsnb.dsp import skim
from ohsnb.skimmer import BandSkimmer

VOICE = 10_489_773_700.0       # a talking USB station's suppressed carrier
CARRIER = 10_489_812_345.0
DATA = 10_489_700_000.0        # a second 400 Bd BPSK beacon: steady, voice-wide
KGSTV = 10_489_626_400.0       # where KG-STV's signal is centred
ERR = 1_234.0                  # the simulated LNB's error (rxCorr would be this)


def band(seconds, stations=(), skimmer=None, ft8=False, seed=3):
    """Feed `seconds` of the simulator's band, with `stations` (kind, dl,
    dBFS) added, through the engine's filter bank into a Skimmer."""
    d = SimDevice(sim_cfg(simRxErrorHz=ERR, simDriftHz=0.0, simSeed=seed))
    d.open()
    for kind, dl, db in stations:
        d.add_station(kind, dl, db, seed=5)
    if ft8:
        act = FT8Activity(np.random.default_rng(seed), bandplan.PRESETS[4]["dl"], -55.0, 0.0)
        act.src = Source(d.geo, int(round(d.fs / 12_000.0)), 0.0)
        d.stations.append(act)
    an = Analysis(d.geo)
    sk = skimmer or skim.Skimmer(d.geo, budget=1.0)
    base = bandplan.DL_LO - d.lnb_lo + ERR - d.rx_if          # Radio._off(DL_LO)
    for _ in range(int(seconds * d.fs / 60_000)):
        X, starts = an.push(d.read(60_000))
        sk.push(X, starts, base)
    return sk


def near(entries, f, hz):
    return [e for e in entries if e["lo"] - hz <= f <= e["hi"] + hz]


class Finds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 32 s: a voice's dial is listed as measured once two looks, 20 s
        # apart, agree (skim.CONFIRM_HZ).
        # No stand-in at KGSTV: the simulator always has a KG-STV station
        # there (devices/kgsim.py), and a second signal on top of it made
        # one entry too wide to be taken for KG-STV.
        cls.sk = band(32.0, [("talk-usb", VOICE, -50.0), ("carrier", CARRIER, -60.0), ("bpsk", DATA, -55.0)])
        cls.entries = cls.sk.entries()

    def test_a_voice_is_listed_with_its_dial_measured(self):
        got = [e for e in near(self.entries, VOICE + 1000.0, 200.0) if e["kind"] == "ssb"]
        self.assertEqual(len(got), 1, self.entries)
        e = got[0]
        self.assertTrue(e["exact"], e)
        self.assertLess(abs(e["dial"] - VOICE), 10.0, e)
        self.assertEqual(e["mode"], "usb")
        self.assertTrue(e["active"])

    def test_a_carrier_is_named_and_placed_to_a_few_hertz(self):
        got = near(self.entries, CARRIER, 100.0)
        self.assertEqual([e["kind"] for e in got], ["carrier"], got)
        self.assertLess(abs(got[0]["f"] - CARRIER), 5.0, got)

    def test_a_steady_voice_wide_signal_is_data_not_a_voice(self):
        got = near(self.entries, DATA, 100.0)
        self.assertEqual([e["kind"] for e in got], ["data"], got)
        self.assertIn("steady", got[0]["why"])
        self.assertIsNone(got[0]["dial"])

    def test_the_known_signal_at_kg_stv_is_named_with_its_dial(self):
        got = near(self.entries, KGSTV, 100.0)
        self.assertEqual([(e["kind"], e["label"]) for e in got], [("known", "KG-STV picture")], got)
        self.assertEqual(got[0]["dial"], 10_489_624_900.0)

    def test_every_beacon_is_one_entry(self):
        beacons = [e["label"] for e in self.entries if e["kind"] == "beacon"]
        self.assertEqual(sorted(beacons), sorted(["Lower beacon (CW)", "Middle beacon (400 Bd BPSK)",
                                                  "Multimedia beacon (HSmodem)", "Upper beacon (CW)"]))

    def test_nothing_else_is_listed_on_an_empty_band(self):
        others = [e for e in self.entries if e["kind"] != "beacon"
                  and not any(near([e], f, 3000.0) for f in (VOICE + 1000.0, CARRIER, DATA, KGSTV))]
        self.assertEqual(others, [])

    def test_entries_are_in_frequency_order(self):
        fs = [e["f"] for e in self.entries]
        self.assertEqual(fs, sorted(fs))


class Confirmed(unittest.TestCase):
    def test_one_answer_is_listed_as_measured_once_not_as_the_dial(self):
        looks = []
        geo = SimDevice(sim_cfg()).geo
        sk = skim.Skimmer(geo, budget=1.0)
        sk.on_look = looks.append
        band(12.0, [("talk-usb", VOICE, -50.0)], skimmer=sk)
        answered = [x for x in looks if x["ok"]]
        self.assertEqual(len(answered), 1, looks)
        e = [x for x in sk.entries() if x["kind"] == "ssb"][0]
        self.assertFalse(e["exact"])
        self.assertEqual(e["measured"], "once")
        self.assertEqual(e["dial"], round(answered[0]["dial"], 1))
        # One look heard speech in the SSB segment: a voice, so "SSB",
        # with its dial still marked as measured once (skim.ssb_label).
        self.assertEqual(e["label"], "SSB")


class Windows(unittest.TestCase):
    def test_ft8_signals_are_one_counted_entry_on_the_calling_frequency(self):
        sk = band(20.0, ft8=True)
        got = [e for e in sk.entries() if e["kind"] == "digital"]
        self.assertEqual(len(got), 1, got)
        e = got[0]
        self.assertEqual((e["label"], e["mode"], e["dial"]), ("FT8", "ft8", 10_489_540_000.0))
        self.assertGreaterEqual(e["count"], 1)
        # Not listed one by one as well.
        self.assertEqual([x for x in sk.entries() if x["kind"] != "digital"
                          and 10_489_540_000.0 <= x["f"] <= 10_489_543_200.0], [])


class Budget(unittest.TestCase):
    @staticmethod
    def priced(budget):
        """A Skimmer whose clock charges by the work in hand, not by the
        machine it runs on. With the real thread_time this test passed on
        x86 and failed every time on the Mac mini M4 (17/10/2026: "4 not
        greater than 4"): a voice look there costs about a tenth of what it
        does on ohs-dev, so even 1 % of a core paid for one look at each of
        the four stations in 14 s and the two budgets came out equal. Here
        every reading of the clock moves it 0.1 ms, plus 0.6 ms for each
        look running: the band alone is under 1 % of a core, and a look
        about 5 %."""
        ticks = [0.0]
        sk = None

        def clock():
            ticks[0] += 0.0001 + 0.0006 * len(sk.looks)
            return ticks[0]

        sk = skim.Skimmer(SimDevice(sim_cfg()).geo, budget=budget, clock=clock)
        return sk

    def test_a_smaller_budget_makes_fewer_looks_not_more_cpu(self):
        stations = [("talk-usb", VOICE, -50.0), ("talk-usb", VOICE + 9_000.0, -50.0),
                    ("talk-usb", VOICE + 18_000.0, -50.0), ("talk-usb", VOICE + 27_000.0, -50.0)]
        rich = band(14.0, stations, skimmer=self.priced(1.0))
        poor = band(14.0, stations, skimmer=self.priced(0.01))
        n_rich = sum(e["looks"] for e in rich.entries())
        n_poor = sum(e["looks"] for e in poor.entries())
        self.assertGreater(n_rich, n_poor)
        # The poor one is in debt by at most the looks it started in credit.
        self.assertLess(poor.cpu(), rich.cpu())

    def test_the_spectrum_thins_when_it_alone_costs_most_of_the_budget(self):
        ticks = [0.0]

        def slow_clock():
            ticks[0] += 0.004          # every section costs 4 ms: a very slow machine
            return ticks[0]

        geo = SimDevice(sim_cfg()).geo
        sk = band(30.0, skimmer=skim.Skimmer(geo, budget=0.02, clock=slow_clock))
        self.assertEqual(sk.level, len(skim.LEVELS) - 1)
        # And still lists what it hears.
        self.assertTrue([e for e in sk.entries() if e["kind"] == "beacon"])


class NarrowJudge(unittest.TestCase):
    RATE = 4000.0

    def keyed(self, wpm=24.0, f=200.0, seconds=2.0, seed=1):
        rng = np.random.default_rng(seed)
        dit = 1.2 / wpm
        n = int(seconds * self.RATE)
        t = np.arange(n) / self.RATE
        on = np.zeros(n, bool)
        pos = 0.0
        while pos < seconds:
            ln = dit * (3 if rng.random() < 0.4 else 1)
            on[int(pos * self.RATE):int((pos + ln) * self.RATE)] = True
            pos += ln + dit * (3 if rng.random() < 0.3 else 1)
        x = on * np.exp(2j * np.pi * f * t)
        return (x + 0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))).astype(np.complex64)

    def test_keyed_is_cw_steady_is_a_carrier(self):
        kind, f, _ = skim.judge_narrow(self.keyed(), self.RATE)
        self.assertEqual(kind, "cw")
        self.assertLess(abs(f - 200.0), 2.0)
        t = np.arange(8000) / self.RATE
        kind, f, _ = skim.judge_narrow(np.exp(2j * np.pi * -150.0 * t).astype(np.complex64), self.RATE)
        self.assertEqual(kind, "carrier")
        self.assertLess(abs(f + 150.0), 2.0)

    def test_psk31_is_not_taken_for_cw(self):
        # Idle PSK31: a phase reversal every symbol, its level dipping to
        # nothing for a few ms each time - swinging, but not in dits.
        n = 8000
        t = np.arange(n) / self.RATE
        sym = (t * 31.25).astype(int)
        env = np.cos(np.pi * (t * 31.25 - sym - 0.5))         # zero at every boundary
        x = (np.abs(env) * np.where(sym % 2, 1, -1) * np.exp(2j * np.pi * 300.0 * t)).astype(np.complex64)
        kind, _f, _ = skim.judge_narrow(x, self.RATE)
        self.assertEqual(kind, "data")

    def test_nothing_there(self):
        rng = np.random.default_rng(2)
        x = (rng.standard_normal(8000) + 1j * rng.standard_normal(8000)).astype(np.complex64)
        self.assertIsNone(skim.judge_narrow(x, self.RATE)[0])


class Engine(unittest.TestCase):
    """The skimmer as the radio runs it: a thread, the feed, the keys."""

    def test_the_feed_and_keys_while_running_and_off_when_switched_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = make_radio(Path(tmp), simSignals=False, simRxErrorHz=0.0, beaconMode="hold", skimBudget=50.0)
            feed = r.subscribe("skim", 16)
            r.start()
            try:
                r.dev.add_station("carrier", CARRIER, -60.0)
                out = run_sim(r, 12.0, feeds=(feed,))
                st = r.state()
                self.assertEqual(st["skimState"], "running")
                self.assertTrue(out["skim"])
                last = out["skim"][-1]["entries"]
                self.assertTrue(near(last, CARRIER, 100.0), last)
                self.assertGreaterEqual(st["skimSignals"], 4)          # the beacons at least
                self.assertGreater(st["skimCpu"], 0.0)
                r.set(skimDecode=False)
                run_sim(r, 0.5)
                self.assertEqual(r.state()["skimState"], "off")
                self.assertIsNone(r.skim)
            finally:
                r.stop()


class Calls(unittest.TestCase):
    """The calls a decoder heard go on the window they were heard in."""

    class FakeRadio:
        THREAD_PREFIX = "test"

        def __init__(self):
            self.geo = SimDevice(sim_cfg()).geo
            self.st = {"skimBudget": 5.0}
            self.published, self.status = [], {}

        def _off(self, dl):
            return 0.0

        def _publish(self, kind, item):
            self.published.append((kind, item))

        def _status(self, **kv):
            self.status.update(kv)

    def test_ft8_calls_heard_in_the_window_are_on_its_entry(self):
        radio = self.FakeRadio()
        sk = BandSkimmer(radio)
        win = {"id": -1, "f": 10_489_540_000.0, "lo": 10_489_540_150.0, "hi": 10_489_543_100.0, "kind": "digital",
               "label": "FT8", "mode": "ft8", "dial": 10_489_540_000.0, "exact": True, "why": "", "snr": 9.0,
               "first": 0.0, "last": 0.0, "active": True, "looks": 0, "count": 3}
        sk.core.entries = lambda wall=None: [dict(win)]
        sk.heard({"mode": "ft8", "call": "G4XYZ", "df": 1200, "dial": 10_489_540_000.0, "t": 1e12})
        sk.heard({"mode": "ft8", "call": "DL1ABC", "df": 1800, "dial": 10_489_540_000.0, "t": 1e12})
        sk.heard({"mode": "ft8", "call": "G4XYZ", "df": 1200, "dial": 10_489_540_000.0, "t": 1e12})
        sk.heard({"mode": "ft8", "call": "F5KLM", "df": 1200, "dial": 10_489_870_000.0, "t": 1e12})  # contest window
        sk.heard({"mode": "psk31", "text": "abc", "df": 1000})
        import time as _t
        real = _t.time
        _t.time = lambda: 1e12
        try:
            sk._publish()
        finally:
            _t.time = real
        kind, item = radio.published[-1]
        self.assertEqual(kind, "skim")
        self.assertEqual(item["entries"][0]["calls"], ["G4XYZ", "DL1ABC"])


if __name__ == "__main__":
    unittest.main()
