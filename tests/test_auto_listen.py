"""Auto-tune and best audio in the engine (Engine.auto_tune / best_audio),
end to end on OpenHamShack NB's simulated transponder: a talking SSB station
is landed from where the operator clicked, RIT is moved instead of the
dial when it is on, refusals change nothing and say why, best audio's
choices are applied once and the operator's controls win afterwards."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import re
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim
from ohscore.dsp import autotune
from ohscore.dsp.bank import Channel
from ohsnb.devices.sim import SimDevice

STATION = 10_489_700_000.0
# The simulator's noise is -101 dBFS/Hz, -67 dBFS in 2.4 kHz, and its
# voice template is 9 dB under its level: -48 dBFS is 10 dB SNR.
LEVEL_10DB = -48.0


class Impulsive(SimDevice):
    """The simulator with an impulse noise source (an electric fence, an
    ignition): a spike every 0.1 s, far above the band's noise."""

    def read(self, n):
        x = super().read(n)
        t0 = getattr(self, "imp_n", 0)
        self.imp_n = t0 + len(x)
        every = int(self.fs * 0.1)
        first = (-t0) % every
        x = x.copy()
        for i in range(first, len(x), every):
            x[i:i + 4] += 0.5
        return x


class Listen(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.radio = None

    def tearDown(self):
        if self.radio is not None:
            self.radio.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, kind="talk-usb", dial_off=0.0, level=LEVEL_10DB, device=None, leak=True, **over):
        """A radio receiving the simulated station. Its voice leaks its
        carrier 30 dB down (`leak`), as many on QO-100 do: past its first
        look auto-tune answers only when that carrier confirms the voice's
        harmonics (autotune.Listener), so without it a listen the first 4 s
        could not settle is refused."""
        mode = kind[-3:] if kind.startswith("talk-") else "usb"
        over = {"rxCorr": 2500.0, "beaconMode": "hold", "mode": mode, "vfo": STATION + dial_off, **over}
        self.radio = r = make_radio(self.tmp, device=device, **over)
        self.toasts = r.subscribe("toast", 64)
        r.start()
        if kind:
            r.dev.add_station(kind, STATION, level, seed=5)
        if kind.startswith("talk-") and leak:
            # The voice template averages 10 dB under a full-scale carrier
            # at the same level, so this is the carrier 30 dB under the voice.
            r.dev.add_station("carrier", STATION, level - 40.0)
        run_sim(r, 0.5)
        return r

    def wait(self, r):
        run_sim(r, autotune.LISTEN_SECONDS + 4.0, until=lambda: r.state()["autoBusy"] == "" and r.listening is None)
        deadline = time.monotonic() + 10
        while r.state()["autoBusy"] and time.monotonic() < deadline:
            time.sleep(0.05)
        return r.state()

    def tune(self, r, dial=None):
        """auto_tune(), pressed again if it refused - as an operator would
        when the voice paused (tests/test_autotune.py holds it to answering
        three times in four, and to never answering wrongly)."""
        for k in range(3):
            r.auto_tune(dial if k == 0 else None)
            s = self.wait(r)
            if not s["autoTuneRefused"]:
                break
        return s

    # -------------------------------------------------------------- auto-tune
    def test_lands_a_usb_station_from_below_and_above(self):
        for off in (-180.0, 220.0):
            with self.subTest(clicked=off):
                r = self.start(dial_off=off)
                r.auto_tune()
                self.assertEqual(r.state()["autoBusy"], "tune")
                s = self.wait(r)
                if s["autoTuneRefused"]:
                    s = self.tune(r)
                self.assertLess(abs(s["vfo"] - STATION), 10.0, s["autoTuneRefused"])
                self.assertTrue(s["autoTune"].startswith(f"{-off:+.0f}"[:2]), s["autoTune"])
                self.assertEqual(s["autoTuneRefused"], "")
                r.stop()
                self.radio = None

    def test_lands_an_lsb_station(self):
        r = self.start("talk-lsb", dial_off=-60.0)
        s = self.tune(r)
        self.assertLess(abs(s["vfo"] - STATION), 10.0, s["autoTuneRefused"])

    def test_a_dial_given_moves_there_first(self):
        # A right-click on a scope: the frequency under the mouse.
        r = self.start(dial_off=3000.0)
        s = self.tune(r, STATION + 45.0)
        self.assertLess(abs(s["vfo"] - STATION), 10.0, s["autoTuneRefused"])

    def test_with_rit_on_it_moves_rit_and_leaves_the_dial(self):
        r = self.start(dial_off=-200.0, rit=100.0, ritOn=True)      # receiving at STATION - 100
        s = self.tune(r)
        self.assertEqual(s["vfo"], STATION - 200.0)
        self.assertLess(abs(s["rxDial"] - STATION), 10.0, s["autoTuneRefused"])
        self.assertLess(abs(s["rit"] - 200.0), 10.0)

    def test_refuses_an_empty_band_and_moves_nothing(self):
        r = self.start(kind="")
        r.auto_tune()
        s = self.wait(r)
        self.assertEqual(s["vfo"], STATION)
        self.assertIn("nothing near the dial", s["autoTuneRefused"])
        self.assertTrue(any(t["level"] == "warn" and "refused" in t["text"] for t in self.toasts.drain()))

    def test_refuses_a_carrier(self):
        r = self.start(kind="carrier", dial_off=-500.0)
        r.auto_tune()
        s = self.wait(r)
        self.assertEqual(s["vfo"], STATION - 500.0)
        self.assertIn("carrier", s["autoTuneRefused"])

    def test_refuses_the_middle_beacon(self):
        # What it was "landed" on in four different places on air, 07/10.
        beacon = 10_489_750_000.0
        r = self.start(kind="", vfo=beacon - 900.0)
        r.auto_tune()
        s = self.wait(r)
        self.assertEqual(s["vfo"], beacon - 900.0)
        self.assertIn("level holds steady", s["autoTuneRefused"])

    def test_moving_the_dial_while_listening_abandons_it(self):
        r = self.start(dial_off=-180.0)
        r.auto_tune()
        run_sim(r, 0.5)
        r.set(vfo=STATION + 5000.0)
        s = self.wait(r)
        self.assertEqual(s["vfo"], STATION + 5000.0)
        self.assertIn("changed while listening", s["autoTuneRefused"])

    # ------------------------------------------- listening until it is sure
    def unsure_until(self, r, seconds):
        """Make the request now listening unsure of the station until it
        has heard `seconds` (the listener's verdict on less is withheld),
        as a voice that pauses or holds its pitch keeps it: the engine's
        side of listening longer, apart from what the measurement says."""
        lis = r.listening["listener"]
        look = lis.look

        def held(iq):
            res = look(iq)
            if len(iq) < seconds * lis.rate - 1:
                lis.result = None
                return None
            return res
        lis.look = held

    def test_it_keeps_listening_counting_the_seconds_then_lands_it(self):
        r = self.start(dial_off=-180.0)
        r.auto_tune()
        self.unsure_until(r, 7.0)
        heard = []
        run_sim(r, 6.5, until=lambda: heard.append(r.state()["autoHeard"]) and False)
        self.assertEqual(r.state()["autoBusy"], "tune")
        self.assertGreaterEqual(max(heard), 5)
        self.assertEqual(sorted(set(heard)), sorted(set(heard), key=heard.index))    # it only counts up
        s = self.wait(r)
        if s["autoTuneRefused"]:
            s = self.tune(r)
        else:
            heard_s = int(re.search(r" in (\d+) s,", s["autoTune"]).group(1))
            self.assertTrue(7 <= heard_s <= autotune.LISTEN_SECONDS, s["autoTune"])
        self.assertLess(abs(s["vfo"] - STATION), 10.0, s["autoTuneRefused"])

    # ------------------------------------------------- an unsure answer's guesses
    def refuse_with_guesses(self, r, guesses):
        """Make the request now listening refuse at its first look, unsure,
        with these guesses (Hz from the dial it listened at) - what the
        Listener says when two offsets a pitch apart tie."""
        lis = r.listening["listener"]

        def unsure(iq):
            lis.result = autotune.Tune(False, why="two offsets fit almost equally", sideband="usb",
                                       details={"guesses": list(guesses), "heard": 12.0})
            return lis.result
        lis.look = unsure

    def test_an_unsure_refusal_offers_its_guesses_and_the_next_presses_try_them(self):
        r = self.start(dial_off=-180.0)
        r.auto_tune()
        self.refuse_with_guesses(r, [180.0, 60.0])
        s = self.wait(r)
        self.assertEqual(s["vfo"], STATION - 180.0)                   # refused: nothing moved
        self.assertIn("Best guess +180 Hz, or +60 Hz", s["autoTuneRefused"])
        self.toasts.drain()
        r.auto_tune()                                                  # no listening: the best guess at once
        s = r.state()
        self.assertIsNone(r.listening)
        self.assertEqual(s["vfo"], STATION)
        self.assertEqual(s["autoTuneRefused"], "")
        self.assertIn("guess 1 of 2", self.toasts.drain()[-1]["text"])
        r.auto_tune()                                                  # the other
        self.assertEqual(r.state()["vfo"], STATION - 120.0)
        r.auto_tune()                                                  # back where it listened
        self.assertEqual(r.state()["vfo"], STATION - 180.0)
        self.assertIn("back where it listened", self.toasts.drain()[-1]["text"])
        r.auto_tune()                                                  # guesses spent: it listens again
        self.assertIsNotNone(r.listening)

    def test_after_an_answer_the_next_best_fit_is_one_press_away(self):
        # A wrong answer is the comb a pitch off, and listening again only
        # hears the same pitch: one more press moves to the next best fit,
        # one after comes back.
        r = self.start(dial_off=-180.0)
        r.auto_tune()
        lis = r.listening["listener"]

        def sure(iq):
            lis.result = autotune.Tune(True, offset=180.0, sideband="usb", coarse=-120.0, pitch=150.0, voiced=100,
                                       details={"alt": 60.0, "heard": 4.0})
            return lis.result
        lis.look = sure
        s = self.wait(r)
        self.assertEqual(s["vfo"], STATION)
        self.assertIn("next best fit (-120 Hz from here)", self.toasts.drain()[-1]["text"])
        r.auto_tune()
        self.assertIsNone(r.listening)
        self.assertEqual(r.state()["vfo"], STATION - 120.0)
        r.auto_tune()
        self.assertEqual(r.state()["vfo"], STATION)
        self.assertIn("back on what it measured", self.toasts.drain()[-1]["text"])
        r.auto_tune()
        self.assertIsNotNone(r.listening)

    def test_a_guess_is_not_applied_once_the_operator_has_tuned(self):
        r = self.start(dial_off=-180.0)
        r.auto_tune()
        self.refuse_with_guesses(r, [180.0])
        self.wait(r)
        r.set(vfo=STATION - 400.0)                                     # tuned by hand since
        r.auto_tune()
        self.assertIsNotNone(r.listening)                              # listens afresh, at the new dial
        self.assertEqual(r.state()["vfo"], STATION - 400.0)

    def test_with_rit_on_a_guess_moves_rit(self):
        r = self.start(dial_off=-180.0, ritOn=True, rit=0.0)
        r.auto_tune()
        self.refuse_with_guesses(r, [180.0])
        self.wait(r)
        r.auto_tune()
        s = r.state()
        self.assertEqual((s["vfo"], s["rit"]), (STATION - 180.0, 180.0))

    def test_moving_the_dial_late_in_a_long_listen_abandons_it(self):
        # Seconds into a listen the operator turns the dial: what was heard
        # is of the old frequency, and nothing is applied when the listener
        # would have finished.
        r = self.start(dial_off=-180.0)
        r.auto_tune()
        self.unsure_until(r, autotune.LISTEN_SECONDS)
        run_sim(r, 6.0)
        self.assertEqual(r.state()["autoBusy"], "tune")
        r.set(vfo=STATION + 5000.0)
        s = self.wait(r)
        self.assertIn("changed while listening", s["autoTuneRefused"])
        run_sim(r, 2.0)
        s = r.state()
        self.assertEqual(s["vfo"], STATION + 5000.0)
        self.assertEqual(s["autoTune"], "")
        self.assertIsNone(r.listening)

    def test_never_sure_it_refuses_at_the_end_saying_how_long_it_listened(self):
        r = self.start(dial_off=-180.0)
        never = lambda *a, **k: {"why": "the voiced frames do not agree on an offset (agreement 0.10, needs 0.15)",
                                 "delta": 0.0, "voiced": 0, "frames": 0, "agree": 0.1, "rival": 1.0,
                                 "pitch": 0.0}  # noqa: E731
        real = autotune.judge
        autotune.judge = never
        self.addCleanup(setattr, autotune, "judge", real)
        r.auto_tune()
        s = self.wait(r)
        self.assertEqual(s["vfo"], STATION - 180.0)
        self.assertEqual(s["autoTuneRefused"],
                         f"after {autotune.LISTEN_SECONDS:.0f} s, the voiced frames do not agree on an offset "
                         f"(agreement 0.10, needs 0.15)")

    def in_passband(self, r):
        """Share of the station's power (over the noise) that falls in the
        receive filter at the dial, from the last two seconds received."""
        s = r.state()
        X = np.concatenate([a for a, _ in r.recent[1]])
        starts = np.concatenate([b for _, b in r.recent[1]])
        ch = Channel(r.geo, r.geo.decimation_for(12000.0), freq=r._off(s["rxDial"]))
        f, P = autotune.psd(ch.take(X, starts))
        P = np.maximum(P - autotune.noise_floor(P, f), 0.0)
        voice = (f > -500.0) & (f < 3500.0)
        inside = (f >= s["filterLo"]) & (f <= s["filterHi"])
        return float(P[inside].sum() / P[voice].sum())

    def test_a_click_on_the_middle_of_the_voice_listens_from_its_carrier(self):
        # Where the mouse is on the scope is the middle of the signal; the
        # dial is the carrier. The last two seconds of spectrum put the
        # dial on the carrier before it listens, so the voice is in the
        # receive filter while it does - and wherever a refusal leaves it.
        r = self.start(dial_off=8000.0)
        run_sim(r, 2.5)
        r.auto_tune(STATION + 1300.0)
        self.assertLess(abs(r.listening["dial"] - STATION), 150.0, r.listening["dial"] - STATION)
        s = self.wait(r)
        if s["autoTuneRefused"]:
            self.assertLess(abs(s["vfo"] - STATION), 150.0, s["autoTuneRefused"])
            s = self.tune(r)
        self.assertLess(abs(s["vfo"] - STATION), 10.0, s["autoTuneRefused"])
        run_sim(r, 2.5)
        self.assertGreater(self.in_passband(r), 0.9)

    def test_a_click_where_no_voice_is_listens_from_the_click(self):
        r = self.start(kind="", dial_off=0.0)
        run_sim(r, 2.5)
        r.auto_tune(STATION + 1300.0)
        self.assertEqual(r.listening["dial"], STATION + 1300.0)
        s = self.wait(r)
        self.assertEqual(s["vfo"], STATION + 1300.0)

    def held_block(self, r):
        """Stop the receive thread inside its next block, after it has
        read the dial and before the block reaches the listener - where it
        was when a right-click retuned on air (07/10/2026). Returns the
        event to release it."""
        inside, go = threading.Event(), threading.Event()
        take = r.vfo_ch.take

        def held(X, starts):
            if not go.is_set():
                inside.set()
                go.wait(10)
            return take(X, starts)
        r.vfo_ch.take = held
        self.assertTrue(inside.wait(10), "the receive thread never reached the channel")
        return go

    def test_a_block_begun_at_the_old_dial_is_not_a_dial_change(self):
        # The right-click always moves the dial; the block under way when
        # it did belongs to the old dial and must be passed over, not taken
        # for the operator retuning.
        r = self.start(dial_off=3000.0)
        go = self.held_block(r)
        r.auto_tune(STATION + 45.0)
        go.set()
        s = self.wait(r)
        self.assertNotIn("changed while listening", s["autoTuneRefused"])
        if not s["autoTuneRefused"]:
            self.assertLess(abs(s["vfo"] - STATION), 10.0, s["autoTune"])

    def test_best_audio_straight_after_a_retune_is_not_a_dial_change(self):
        # Shift+A pressed while the block from before the operator's last
        # turn of the dial is still going through.
        r = self.start(dial_off=3000.0, nr=False)
        go = self.held_block(r)
        r.set(vfo=STATION)
        r.best_audio()
        go.set()
        s = self.wait(r)
        self.assertEqual(s["autoAudioRefused"], "")
        self.assertTrue(s["nr"], s["autoAudio"])

    def test_the_dial_moved_before_anything_was_heard_still_abandons_it(self):
        # Passing over the old dial's block must not mean waiting forever
        # for one at the dial asked for once the operator has gone elsewhere.
        r = self.start(dial_off=3000.0)
        go = self.held_block(r)
        r.auto_tune(STATION + 45.0)
        r.set(vfo=STATION - 5000.0)
        go.set()
        s = self.wait(r)
        self.assertEqual(s["vfo"], STATION - 5000.0)
        self.assertIn("changed while listening", s["autoTuneRefused"])

    def test_only_in_voice_modes_and_one_at_a_time(self):
        r = self.start(mode="cw")
        with self.assertRaises(ValueError):
            r.auto_tune()
        r.set(mode="usb")
        r.auto_tune()
        with self.assertRaises(ValueError):
            r.best_audio()
        self.wait(r)

    # ------------------------------------------------------------ best audio
    def test_best_audio_applies_once_and_the_operator_wins(self):
        r = self.start(nr=False, agc="fast", filterLo=100.0, filterHi=3500.0)
        r.best_audio()
        s = self.wait(r)
        self.assertEqual(s["autoAudioRefused"], "")
        self.assertTrue(s["nr"])                 # 10 dB: weak enough for NR
        self.assertEqual(s["agc"], "slow")
        self.assertLessEqual(s["filterHi"], 2600.0)
        self.assertIn("NR", s["autoAudio"])
        self.assertIn("agc: slow", s["autoAudioWhy"])
        # Nothing keeps adjusting: the operator's change stands.
        r.set(nr=False, filterHi=3000.0)
        run_sim(r, 2.0)
        s = r.state()
        self.assertFalse(s["nr"])
        self.assertEqual(s["filterHi"], 3000.0)

    def test_best_audio_on_a_strong_station_leaves_nr_off(self):
        r = self.start(level=LEVEL_10DB + 20.0, nr=True)
        r.best_audio()
        s = self.wait(r)
        self.assertFalse(s["nr"], s["autoAudio"])
        self.assertEqual(s["agc"], "medium")

    def test_best_audio_hears_impulses_and_blanks_them(self):
        r = self.start(level=LEVEL_10DB + 20.0, device=Impulsive)
        r.best_audio()
        s = self.wait(r)
        self.assertTrue(s["nb"], s["autoAudio"])
        self.assertIn("impulses a second", s["autoAudioWhy"])

    def test_best_audio_refuses_an_empty_passband(self):
        r = self.start(kind="", nr=False, filterHi=2700.0)
        r.best_audio()
        s = self.wait(r)
        self.assertIn("nothing in the passband", s["autoAudioRefused"])
        self.assertFalse(s["nr"])
        self.assertEqual(s["filterHi"], 2700.0)


class HamRecentre(unittest.TestCase):
    """OpenHamShack HAM retunes the radio itself when the dial leaves the span
    it can see: until that has reached the samples, what the channel holds
    is of the old centre, and none of it may be listened to."""

    def test_nothing_is_heard_from_before_the_radio_moved(self):
        from ham_helpers import close, make_radio as ham_radio, pump
        r = ham_radio(vfo=144_300_000.0, mode="usb")
        self.addCleanup(close, r)
        r.start()
        pump(r, 5, until=lambda: r.rx_samples > r.geo.fs)
        heard = []
        feed = r._listen_feed

        def spy(iq, rx_dial):
            L = r.listening
            n = L["n"] if L is not None else 0
            moving = not r._rx_settled()
            feed(iq, rx_dial)
            if L is not None and L["n"] > n:
                heard.append(moving)
        r._listen_feed = spy
        r.auto_tune(145_200_000.0)          # 900 kHz up: off the span, so the radio re-centres
        pump(r, 20, until=lambda: r.listening is None and not r.state()["autoBusy"])
        self.assertTrue(heard)
        self.assertFalse(any(heard), "audio was taken while the radio was still moving")


if __name__ == "__main__":
    unittest.main()
