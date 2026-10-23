"""Radio's Decoders view, "Decode here as" and Settings › Decoders
(ohscore/ui/decodersview.py, wired in ohsradio/ui/mainwindow.py and
ohsradio/ui/settings.py; RADIO-SDR-PLAN §4.5), driven as an operator would
on the band simulator: Add starts an RTTY session at the typed frequency
with the chosen speed and shift, its card copies the simulated station,
Tune puts the dial on it in RTTY, Stop ends it, a refusal is said in the
view, the scope's right-click starts one where the mouse is, and Settings
lists the codecs and their sentences. Nothing here keys."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ham_helpers import make_radio

from ohscore import sdr

RTTY_HZ = 14_091_750.0 + 1500.0          # seed 2's 20 m RTTY station (test_decoders.py)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class DecodersWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: self.errors.append((t, v, tb))
        self.wins = []

    def tearDown(self):
        for win, bridge in self.wins:
            win.close()
            bridge.stop()
        self.app.processEvents()
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.errors:
            import traceback
            self.fail("exceptions in Qt slots:\n" + "".join("".join(traceback.format_exception(*e))
                                                            for e in self.errors))

    def window(self, **over):
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        radio = make_radio(**{"simSeed": 2, "simHourUtc": 14.0, "vfo": 14_070_000.0, "mode": "usb", **over})
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.settle_until(lambda: radio.state()["running"])
        return win, bridge, radio

    def settle_until(self, cond, sec=5.0):
        end = time.monotonic() + sec
        while not cond() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        return cond()

    def test_add_copies_the_station_tune_puts_the_dial_there_and_stop_ends_it(self):
        win, bridge, radio = self.window()
        self.assertIn("decoders", win.extra_views)
        win.show_view("decoders")
        view = win.decoders_view
        self.assertEqual(view.pick.currentData(), "rtty")
        self.assertIn("baud", view.param_widgets)
        view.param_widgets["shift"].setCurrentIndex(view.param_widgets["shift"].findData(170.0))
        view.freq.setText(f"{RTTY_HZ / 1e6:.6f}")
        view.add()
        self.assertEqual(len(view.cards), 1, view.status.text())
        sid, card = next(iter(view.cards.items()))
        self.assertTrue(self.settle_until(lambda: "CQ TEST" in card.term.toPlainText(), 60))
        self.assertIn("RTTY · 45.45/170", card.title.text())
        card.tune_btn.clicked.emit()
        self.assertTrue(self.settle_until(lambda: radio.st["mode"] == "rtty"))
        self.assertAlmostEqual(radio.st["vfo"], RTTY_HZ - 1000.0, delta=20.0)
        self.settle_until(lambda: len(view.cards) == 2)       # the mode's own decoder now shows too
        self.assertIn("the mode's decoder", " ".join(c.title.text() for c in view.cards.values()))
        card.stop_btn.clicked.emit()
        self.assertTrue(self.settle_until(lambda: sid not in view.cards))
        self.assertFalse(radio.state()["keyed"])

    def test_tight_drops_the_tab_but_keeps_the_view(self):
        win, bridge, radio = self.window()
        self.assertIn("decoders", [v for v, _ in win.views.options])
        win.resize(1024, 600)
        self.settle_until(lambda: win.tier == "tight")
        self.assertEqual(win.tier, "tight")
        self.assertNotIn("decoders", [v for v, _ in win.views.options])
        win.show_view("decoders")
        self.assertIs(win.stack.currentWidget(), win.decoders_view)
        win.resize(1600, 960)
        self.settle_until(lambda: win.tier != "tight")
        self.assertIn("decoders", [v for v, _ in win.views.options])

    def test_a_refusal_is_said_in_the_view(self):
        win, bridge, radio = self.window()
        win.show_view("decoders")
        view = win.decoders_view
        view.freq.setText("7.050")
        view.add()
        self.assertIn("is too far from the dial", view.status.text())
        self.assertEqual(view.cards, {})

    def test_decode_here_as_starts_a_session_where_the_mouse_is(self):
        win, bridge, radio = self.window()
        items = win.scope_menu_items(RTTY_HZ)
        sub = next(fn for text, fn, _ in items if text == "Decode here as")
        label, start = next((t, fn) for t, fn in sub if t == "RTTY")
        start()
        self.assertEqual([(s["decoder"], s["freqHz"]) for s in radio.decoders.sessions()], [("rtty", RTTY_HZ)])
        win.scope_menu(RTTY_HZ, win.wide.mapToGlobal(win.wide.rect().center()))
        menus = [a.menu() for a in win.scope_menu_open.actions() if a.menu() is not None]
        self.assertEqual([m.title() for m in menus], ["Decode here as"])
        win.scope_menu_open.close()

    def test_settings_lists_the_codecs_and_the_limits(self):
        from ohsradio.ui.settings import SettingsDialog
        win, bridge, radio = self.window()
        dlg = SettingsDialog(bridge, win.prefs, win)
        texts = [dlg.codec_rows.itemAt(i).widget().text() for i in range(dlg.codec_rows.count())]
        self.assertEqual([t.split(":")[0] for t in texts], ["codec2", "faad2", "fdk-aac", "mbelib"])
        self.assertTrue(all(len(t) > len("mbelib: ") for t in texts))
        self.assertIn("decodersMax", dlg.fields)
        self.assertIn("decodeCpuMax", dlg.fields)
        dlg._fill_codecs(rescan=True)
        self.assertEqual(dlg.codec_rows.count(), 4)
        dlg.close()


if __name__ == "__main__":
    unittest.main()
