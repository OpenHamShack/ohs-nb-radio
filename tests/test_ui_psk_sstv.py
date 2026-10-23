"""Radio's window with PSK and SSTV on shack_sdr (RADIO-SDR-PLAN §8.5 M2),
driven as an operator would, on the band simulator with known stations on
the air (HamSim.add_station; test_ham_psk_sstv has the engine side):

- **PSK, several stations:** a click on a station on the zoom decodes it
  too - its mark on the scope, its line under "Also decoding" with what
  it sends - a second click stops it, and shift-click still tunes it onto
  the decoder's own channel, whose text stays in the terminal.
- **SSTV as the mode:** the picture paints in on the SSTV panel, and the
  finished one joins its gallery.
- **The Decoders view:** an SSTV session's card paints its picture and
  then shows it among its recent ones; a PSK session with two stations
  shows a line for each.

Nothing here keys."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from ham_helpers import make_radio

from ohscore import sdr
from ohscore.devices import simsignals as sg
from ohscore.modes import psk

DIAL = 14_101_000.0
LEVEL = -58.0


def psk_air(text, centre, variant="psk31"):
    a = psk.Encoder().render(text=text, variant=variant, center=centre)
    return sg.analytic(np.concatenate([np.zeros(12_000, np.float32), a, np.zeros(24_000, np.float32)]))


def sstv_air():
    from shack_sdr import sstv
    audio, _sent = sstv.testsig("robot36", rate=12_000.0, lead_s=1.0, tail_s=2.0)
    return sg.analytic(np.concatenate([audio, np.zeros(len(audio), np.float32)]))


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class PskAndSstvWindow(unittest.TestCase):
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
        radio = make_radio(**{"simSignals": False, "simSeed": 3, "vfo": DIAL, "mode": "usb", **over})
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

    def click_zoom(self, win, audio_hz, shift=False):
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest
        z = win.zoom
        x = int(round(z.fmap.x(DIAL + audio_hz)))
        y = int(z.r_wf.center().y())
        mods = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
        QTest.mouseClick(z, Qt.MouseButton.LeftButton, mods, QPoint(x, y))

    def test_a_click_on_the_zoom_decodes_a_station_too_and_a_second_stops_it(self):
        win, bridge, radio = self.window(mode="psk31")
        radio.dev.add_station("own", DIAL, psk_air("CQ DE G4AAA G4AAA K ", 1000.0), LEVEL)
        radio.dev.add_station("other", DIAL, psk_air("QRZ DE M0BBB M0BBB ", 1630.0), LEVEL)
        panel = win.panels["text"]
        self.settle_until(lambda: win.zoom.fmap is not None and win.zoom.width() > 0)
        self.click_zoom(win, 1630.0)
        self.assertTrue(self.settle_until(lambda: radio.st["pskChannels"]))
        (got,) = radio.st["pskChannels"]
        self.assertAlmostEqual(got, 1630.0, delta=15.0)
        self.assertEqual(radio.st["vfo"], DIAL)                    # a click no longer tunes in PSK
        # Its mark on the zoom, and its line under "Also decoding".
        flags = [t for _x, _y, t, _c in win.zoom.mode_flags(DIAL)]
        self.assertIn(f"+ {got:.0f}", flags)
        self.assertTrue(panel.more.isVisible())
        self.assertTrue(self.settle_until(lambda: "M0BBB M0BBB" in panel.more.item(0).text(), 60),
                        panel.more.item(0).text())
        self.assertTrue(self.settle_until(lambda: "G4AAA G4AAA K" in panel.term.toPlainText(), 60))
        self.assertNotIn("M0BBB", panel.term.toPlainText())
        # A click on it again stops it; one on the decoder's own channel is
        # said, not added.
        self.click_zoom(win, got + 8.0)
        self.assertTrue(self.settle_until(lambda: radio.st["pskChannels"] == []))
        self.click_zoom(win, 1005.0)
        self.app.processEvents()
        self.assertEqual(radio.st["pskChannels"], [])
        self.assertIn("Click a station", panel.more.item(0).text())
        # Shift-click tunes the station onto the decoder's own channel.
        self.click_zoom(win, 1630.0, shift=True)
        self.assertTrue(self.settle_until(lambda: abs(radio.st["vfo"] - (DIAL + 630.0)) <= 10.0))
        self.assertEqual(radio.st["pskChannels"], [])

    def test_stop_all_and_rtty_has_no_stations_list(self):
        win, bridge, radio = self.window(mode="psk63")
        radio.set(pskChannels=[1400.0, 2200.0])
        panel = win.panels["text"]
        self.assertTrue(self.settle_until(lambda: panel.more.count() == 2))
        self.assertEqual([panel.more.item(i).text().split()[0] for i in range(2)], ["1400", "2200"])
        panel.more_clear.clicked.emit()
        self.assertTrue(self.settle_until(lambda: radio.st["pskChannels"] == []))
        bridge.set(mode="rtty")
        self.assertTrue(self.settle_until(lambda: not panel.more.isVisible()))

    def test_sstv_mode_paints_the_picture_and_adds_it_to_the_gallery(self):
        win, bridge, radio = self.window(mode="sstv")
        panel = win.panels["image"]
        self.assertEqual(panel.list.count(), 1)                   # "Received pictures appear here"
        radio.dev.add_station("sstv", DIAL, sstv_air(), LEVEL)
        self.assertTrue(self.settle_until(lambda: panel.pic.buf is not None and panel.pic.line > 100, 60))
        self.assertEqual(panel.pic.buf.shape, (240, 320))
        self.assertTrue(self.settle_until(lambda: panel.list.item(0).data(256) is not None, 60))
        path = panel.list.item(0).data(256)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.dirname(path), str(radio.sstv_dir()))

    def test_the_decoders_view_paints_an_sstv_session_and_lists_its_pictures(self):
        win, bridge, radio = self.window()
        radio.dev.add_station("sstv", DIAL, sstv_air(), LEVEL)
        win.show_view("decoders")
        view = win.decoders_view
        view.pick.setCurrentIndex(view.pick.findData("sstv"))
        self.assertIn("mode", view.param_widgets)
        modes = view.param_widgets["mode"]
        self.assertEqual(modes.count(), 1 + len(sdr.load().sstv.modes()))
        self.assertEqual(modes.itemText(1), "Martin M1")
        view.add()                                               # empty: the dial plus 1900 Hz
        self.assertEqual([(s["decoder"], s["freqHz"]) for s in radio.decoders.sessions()],
                         [("sstv", DIAL + 1900.0)])
        sid, card = next(iter(view.cards.items()))
        self.assertIsNotNone(card.pic)
        self.assertFalse(card.term.isVisible())
        self.assertTrue(self.settle_until(lambda: card.pic.buf is not None and card.pic.line > 100, 60))
        self.assertTrue(self.settle_until(lambda: card.thumbs.count() == 1, 60))
        self.assertTrue(card.thumbs.isVisible())
        self.assertIn("SSTV · any mode", card.title.text())
        # Tune: the dial 1900 Hz below the session's frequency, in SSTV.
        card.tune_btn.clicked.emit()
        self.assertTrue(self.settle_until(lambda: radio.st["mode"] == "sstv"))
        self.assertAlmostEqual(radio.st["vfo"], DIAL, delta=1.0)

    def test_the_decoders_view_shows_a_line_per_psk_station(self):
        win, bridge, radio = self.window()
        there = DIAL + 20_000.0
        radio.dev.add_station("a", there, psk_air("ALPHA DE G4AAA ", 1000.0), LEVEL)
        radio.dev.add_station("b", there, psk_air("BRAVO DE M0BBB ", 1700.0), LEVEL)
        win.show_view("decoders")
        view = win.decoders_view
        view.pick.setCurrentIndex(view.pick.findData("psk"))
        view.freq.setText(f"{(there + 1000.0) / 1e6:.6f}")
        view.param_widgets["channels"].setText("0, 700")
        view.add()
        self.assertEqual(radio.decoders.sessions()[0]["params"]["channels"], "0,700")
        sid, card = next(iter(view.cards.items()))
        self.assertIn("PSK · 31.25 Bd 2 stations", card.title.text())
        self.assertTrue(self.settle_until(lambda: "G4AAA" in card.lines.text() and "M0BBB" in card.lines.text(), 60),
                        card.lines.text())
        first, second = card.lines.text().splitlines()
        self.assertIn("ALPHA DE G4AAA", first)
        self.assertIn("BRAVO DE M0BBB", second)
        self.assertFalse(card.term.isVisible())


if __name__ == "__main__":
    unittest.main()
