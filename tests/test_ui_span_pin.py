"""The desktop and a pinned span (test_ham_span_pin has the engine's side):
every way of tuning out of the span the background decoders hold asks
first, with the sessions it would stop; No leaves everything as it was
(and a knob turned on past the edge is not asked again at once); Yes stops
them and tunes. The wide scope says the span is held and where each
session is, and greys what lies beyond it."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ham_helpers import close, make_radio, pump

from ohscore import sdr

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

RTTY_HZ = 14_091_750.0 + 1500.0      # seed 2's 20 m RTTY station (test_decoders)
DIAL = 14_070_000.0


@unittest.skipUnless(HAVE_QT and sdr.available(), "needs PyQt6 and shack_sdr")
class AskingFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        from ohscore.ui.bridge import Bridge
        from ohsradio.ui.face import HamFace
        self.r = make_radio(simSeed=2, simHourUtc=14.0, vfo=DIAL, mode="usb")
        self.r.start()
        self.addCleanup(close, self.r)
        self.bridge = Bridge(self.r)
        self.bridge.face = HamFace(self.bridge)
        self.bridge.st = self.r.state()
        self.asked, self.answer = [], False
        self.bridge.asker = lambda text: (self.asked.append(text), self.answer)[1]
        self.toasts = []
        self.bridge.toast.connect(lambda t: self.toasts.append(t["text"]))
        self.sess = self.r.decoders.start("rtty", RTTY_HZ)

    def test_no_leaves_everything_and_a_knob_past_the_edge_is_not_asked_again_at_once(self):
        self.assertFalse(self.bridge.set(vfo=7_050_000.0))
        self.assertEqual(self.asked, ["Tuning to 7.0500 MHz stops: RTTY on 14.0933 MHz. Continue?"])
        self.assertEqual(self.r.state()["vfo"], DIAL)
        self.assertEqual([s["id"] for s in self.r.decoders.sessions()], [self.sess["id"]])
        # The next step of the knob: told, not asked.
        self.assertFalse(self.bridge.set(vfo=7_049_000.0))
        self.assertEqual(len(self.asked), 1)
        self.assertTrue(self.toasts[-1].startswith("Tuning to 7.0490 MHz stops RTTY on 14.0933 MHz"))
        # Inside the span nothing is asked at all.
        self.bridge.declined_at = -1e9
        self.assertTrue(self.bridge.set(vfo=14_250_000.0))
        self.assertEqual(len(self.asked), 1)

    def test_yes_stops_them_and_tunes(self):
        self.answer = True
        self.assertTrue(self.bridge.set(vfo=7_050_000.0))
        self.assertEqual(self.r.state()["vfo"], 7_050_000.0)
        self.assertEqual(self.r.decoders.sessions(), [])
        self.assertFalse(self.r.state()["span"]["pinned"])

    def test_a_band_button_a_memory_and_a_mode_ask_too(self):
        self.assertFalse(self.bridge.tune_with(lambda: self.r.band("40m")))
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.r.state()["band"], "20m")
        self.bridge.declined_at = -1e9
        self.r.save_memory("away", 7_100_000.0, "lsb")
        self.answer = True
        self.assertTrue(self.bridge.tune_with(lambda: self.r.recall("away")))
        self.assertEqual((self.r.state()["vfo"], self.r.decoders.sessions()), (7_100_000.0, []))
        self.assertEqual(len(self.asked), 2)

    def test_dab_asks_in_its_own_words(self):
        self.assertFalse(self.bridge.ask_stop(self.r.decoders.pinned_by(), None))
        self.assertEqual(self.asked, ["Playing DAB stops: RTTY on 14.0933 MHz. Continue?"])


@unittest.skipUnless(HAVE_QT and sdr.available(), "needs PyQt6 and shack_sdr")
class TheWideScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def test_it_says_the_span_is_held_and_where_each_session_is(self):
        from ohscore.ui.bridge import Bridge
        from ohscore.ui.prefs import Prefs
        from ohscore.ui.scope import ScopeView
        from ohsradio.ui.face import HamFace
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        r = make_radio(simSeed=2, simHourUtc=14.0, vfo=DIAL, mode="usb")
        r.start()
        self.addCleanup(close, r)
        pump(r, 5, until=lambda: r.state().get("spanLo"))
        bridge = Bridge(r)
        bridge.face = HamFace(bridge)
        bridge.st = r.state()
        v = ScopeView(bridge, Prefs(os.path.join(tmp, "ui.json")), "wide")
        v.resize(1000, 420)
        v.show()
        self.app.processEvents()
        self.addCleanup(v.close)
        self.assertEqual(v.span_layout(), ([], None))
        r.decoders.start("rtty", RTTY_HZ)
        bridge.st = r.state()
        v.update()
        marks, edges = v.span_layout()
        self.assertEqual([cap for _x, cap in marks], ["RTTY"])
        self.assertAlmostEqual(marks[0][0], v.fmap.x(RTTY_HZ), places=3)
        sp = bridge.st["span"]
        self.assertEqual(edges, (v.fmap.x(sp["loHz"]), v.fmap.x(sp["hiHz"])))
        v.grab()                        # it paints


if __name__ == "__main__":
    unittest.main()
