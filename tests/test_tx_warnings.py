"""The transmit card's one standing warning (Engine.tx_warn, status
txWarning) and OpenHamShack NB's own-signal-over-the-beacon warning that is its
busiest user: on only when clearly over, once per run of over readings,
off once back under, kept in the past tense after the over. Until 0.1.10
both were toasts, and the beacon one fired on every TX-lock measurement,
"0.0 dB ABOVE" included."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from helpers import make_radio, run_sim, wait_rx_lock
from ohsnb.radio import LEVEL_REARM_DB, LEVEL_WARN_DB

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


class Radios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def radio(self, start=False, **over):
        r = make_radio(self.tmp, **over)
        self.radios.append(r)
        if start:
            r.start()
        return r


class Standing(Radios):
    def test_the_most_serious_shows_and_clearing_it_reveals_the_next(self):
        r = self.radio()
        self.assertEqual(r.state()["txWarning"], {})
        r.tx_warn("a", "an info note", "info")
        r.tx_warn("b", "a warning", "warn")
        r.tx_warn("c", "a later info note", "info")
        self.assertEqual(r.state()["txWarning"], {"key": "b", "level": "warn", "text": "a warning"})
        r.tx_warn("d", "an error", "error")
        self.assertEqual(r.state()["txWarning"]["key"], "d")
        r.tx_clear("d")
        self.assertEqual(r.state()["txWarning"]["key"], "b")
        r.tx_clear("b", "nothing-by-this-name")
        self.assertEqual(r.state()["txWarning"]["key"], "c")      # the most recent of the infos
        r.tx_clear("a", "c")
        self.assertEqual(r.state()["txWarning"], {})

    def test_priority_beats_recency_and_rewording_keeps_its_place(self):
        r = self.radio()
        r.tx_warn("power", "over the licence", "warn", priority=2, detail="the long reason")
        r.tx_warn("plan", "band plan", "warn", priority=1)
        self.assertEqual(r.state()["txWarning"],
                         {"key": "power", "level": "warn", "text": "over the licence", "detail": "the long reason"})
        r.tx_warn("x", "same priority, newer", "warn", priority=2)
        self.assertEqual(r.state()["txWarning"]["key"], "x")
        # A changed figure in "power" is the same warning, not a newer one.
        r.tx_warn("power", "over the licence, now by more", "warn", priority=2)
        self.assertEqual(r.state()["txWarning"]["key"], "x")

    def test_none_of_it_is_a_toast(self):
        r = self.radio()
        toasts = r.subscribe("toast", 16)
        r.tx_warn("a", "standing", "error")
        r.tx_clear("a")
        self.assertEqual(toasts.drain(), [])


class LevelWarning(Radios):
    """The readings are fed to the warning as TX lock's measurements would
    be; the whole path, from the simulated transponder, is in OnTheAir."""

    def feed(self, r, readings):
        shown = []
        for vs in readings:
            r._level_warn(vs, False)
            shown.append(r.state()["txWarning"].get("text", ""))
        return shown

    def test_level_with_the_beacon_is_not_over_it(self):
        r = self.radio()
        r._level_new_over()
        # Seen on air: a signal sitting on the beacon's level read "0.0 dB ABOVE".
        shown = self.feed(r, [0.0, 0.04, 0.2, 0.3, 0.49, 0.1, -0.2])
        self.assertEqual(shown, [""] * 7)

    def test_once_per_over_sequence_with_hysteresis(self):
        self.assertGreater(LEVEL_WARN_DB, LEVEL_REARM_DB)
        r = self.radio()
        r._level_new_over()
        with self.assertLogs(r.log, "INFO") as logs:
            shown = self.feed(r, [0.6, 0.9, 0.45, 0.1, 0.55, -0.1, 0.3, 0.45, 0.7])
        # On at +0.6, its figure kept current, held through the dip to +0.1
        # (still over the beacon), off below 0 dB, and not back on until
        # +0.5 is reached again.
        self.assertIn("0.6 dB above the beacon", shown[0])
        self.assertIn("0.9 dB above the beacon", shown[1])
        self.assertIn("0.1 dB above the beacon", shown[3])
        self.assertTrue(all(shown[:5]))
        self.assertEqual(shown[5:8], ["", "", ""])
        self.assertIn("0.7 dB above the beacon", shown[8])
        standing = [m for m in logs.output if "(standing)" in m]
        self.assertEqual(len(standing), 2, logs.output)       # two over sequences, two log lines

    def test_it_stays_after_the_over_until_the_next(self):
        r = self.radio()
        r._level_new_over()
        self.feed(r, [1.0, 2.5, 1.5])
        r._level_after_over()
        w = r.state()["txWarning"]
        self.assertEqual(w["key"], "level")
        self.assertIn("last over reached 2.5 dB above the beacon", w["text"])
        r._level_new_over()
        self.assertEqual(r.state()["txWarning"], {})

    def test_an_over_that_came_back_under_leaves_nothing(self):
        r = self.radio()
        r._level_new_over()
        self.feed(r, [1.0, -0.5])
        r._level_after_over()
        self.assertEqual(r.state()["txWarning"], {})

    def test_the_ic9700_says_whose_power_to_reduce(self):
        r = self.radio()
        r._level_new_over()
        r._level_warn(1.2, True)
        self.assertIn("reduce power on the IC-9700", r.state()["txWarning"]["text"])


class OnTheAir(Radios):
    """Through the simulated transponder. In the simulator a carrier at
    -20 dB TX gain lands at the beacon's level (tests/test_radio.py)."""

    def test_an_over_well_above_the_beacon_warns_once_standing_and_no_toasts(self):
        # callsign + licenceClass: a known licence, so the "licence"
        # warning (no class set) does not also stand and outrank "level".
        r = self.radio(start=True, mode="cw", vfo=10_489_520_000.0, txGain=-14.0, txGainCeiling=0.0,
                       levelMode="manual", callsign="GM4BRI", licenceClass="full")
        self.assertTrue(wait_rx_lock(r))
        run_sim(r, 1.5)
        toasts = r.subscribe("toast", 256)
        r.ptt(True)
        run_sim(r, 6.0, until=lambda: r.state()["txWarning"].get("key") == "level")
        w = r.state()["txWarning"]
        self.assertEqual((w.get("key"), w.get("level")), ("level", "warn"), r.state()["vsBeacon"])
        self.assertIn("dB above the beacon", w["text"])
        run_sim(r, 2.0)
        r.ptt(False)
        run_sim(r, 0.5, until=lambda: not r.state()["keyed"])
        run_sim(r, 0.5)
        self.assertIn("last over reached", r.state()["txWarning"]["text"])
        said = [t["text"] for t in toasts.drain()]
        self.assertFalse(any("beacon" in t.lower() and "above" in t.lower() for t in said), said)
        # Manual is warn only: the gain was not touched.
        self.assertEqual(r.state()["txGain"], -14.0)
        # The next over, well under the beacon, starts with a clean card.
        r.set(txGain=-30.0)
        r.ptt(True)
        run_sim(r, 4.0)
        self.assertEqual(r.state()["txWarning"], {})
        r.ptt(False)

    def test_limit_mode_trims_and_says_so_in_the_standing_line(self):
        # callsign + licenceClass: a known licence, so the "licence"
        # warning (no class set) does not also stand and outrank "trim".
        r = self.radio(start=True, mode="cw", vfo=10_489_520_000.0, txGain=-5.0, txGainCeiling=0.0,
                       levelMarginDb=6.0, levelMode="limit", callsign="GM4BRI", licenceClass="full")
        self.assertTrue(wait_rx_lock(r))
        run_sim(r, 1.5)
        toasts = r.subscribe("toast", 256)
        r.ptt(True)
        run_sim(r, 6.0)
        self.assertLess(r.state()["txGain"], -20.0)
        r.ptt(False)
        run_sim(r, 0.5)
        said = [t["text"] for t in toasts.drain()]
        self.assertFalse(any("trimmed" in t for t in said), said)
        # The over started 15 dB over the beacon; the trim brought it back
        # under during the over, so that warning has cleared and the trim
        # note, which explains the moved slider, is what is left.
        w = r.state()["txWarning"]
        self.assertEqual((w["key"], w["level"]), ("trim", "info"))
        self.assertIn("Transmit gain trimmed", w["text"])


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Card(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def test_the_line_shows_changes_and_goes(self):
        from ohscore.ui import theme
        from ohscore.ui.controls import StandingWarning
        w = StandingWarning()
        self.assertTrue(w.isHidden())
        w.set_warning({"key": "level", "level": "warn", "text": "Your downlink is 1.0 dB above the beacon"})
        self.assertFalse(w.isHidden())
        self.assertEqual(w.text(), "Your downlink is 1.0 dB above the beacon")
        self.assertIn(theme.t()["warn"], w.styleSheet())
        w.set_warning({"key": "rig-aim", "level": "error", "text": "transmitting where NB would not",
                       "detail": "why"})
        self.assertEqual(w.text(), "transmitting where NB would not")
        self.assertIn(theme.t()["err"], w.styleSheet())
        self.assertEqual(w.toolTip(), "why")
        w.set_warning({})
        self.assertTrue(w.isHidden())
        self.assertEqual(w.key, "")

    def test_nbs_transmit_card_follows_the_state(self):
        from ohsnb.ui.rail import TransmitCard
        from ohsnb import state

        # Only what the card reads. Since the transmit-state line (txstate)
        # it also asks whether the licence still locks a key-up and whether
        # the radio is receive-only: here the licence is acknowledged and
        # there is no radio, so the warning is the only thing that moves.
        class Bridge:
            st = state.defaults()
            radio = None

            def set(self, **kw):
                pass

            def licence_locked(self):
                return False
        b = Bridge()
        card = TransmitCard(b)
        self.assertTrue(card.warning.isHidden())
        b.st["txWarning"] = {"key": "level", "level": "warn", "text": "Your downlink is 2.0 dB above the beacon"}
        card.on_state({"txWarning": b.st["txWarning"]})
        self.assertFalse(card.warning.isHidden())
        self.assertIn("2.0 dB above", card.warning.text())
        b.st["txWarning"] = {}
        card.on_state({"txWarning": {}})
        self.assertTrue(card.warning.isHidden())


if __name__ == "__main__":
    unittest.main()
