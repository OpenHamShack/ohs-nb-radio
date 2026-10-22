"""OpenHamShack Radio's band buttons and band-plan overlay (Brian,
13/10/2026), driven through the window on the band simulator as an
operator would: press a band, see where it lands, see the plan drawn over
the scope there.

- The overlay: the wide scope's strip shows the plan in force for the
  band under the dial - for a UK callsign, RSGB 2026 - read back the way
  an operator reads it, by hovering over the strip.
- The buttons: a first visit lands on the FT8 dial from a digital mode,
  else at the start of the plan's SSB segment (LSB below 10 MHz, USB
  above); a band left and come back to is where it was left.
- Coverage: the row holds only the bands the receiver covers.
- Nothing here keys: the simulator's transmitter is never written."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QToolTip
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from ham_helpers import make_radio

from ohsradio import bands, plans


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class BandButtons(unittest.TestCase):
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

    # ------------------------------------------------------------------ helpers
    def window(self, **over):
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        radio = make_radio(**over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.settle(0.3)
        return win, bridge, radio

    def settle(self, sec, until=None):
        end = time.monotonic() + sec
        while time.monotonic() < end and not (until is not None and until()):
            self.app.processEvents()
            time.sleep(0.01)

    def press(self, win, name):
        """Click band `name` on the band row, as the operator does."""
        win.bandbar.repaint()                      # lays the row out for what the receiver covers now
        r = next(rect for rect, kind, key in win.bandbar.cells if kind == "band" and key == name)
        QTest.mouseClick(win.bandbar, Qt.MouseButton.LeftButton,
                         pos=QPoint(int(r.center().x()), int(r.center().y())))
        self.settle(0.2)

    def on_row(self, win) -> list[str]:
        win.bandbar.repaint()
        return [key for _r, kind, key in win.bandbar.cells if kind == "band"]

    def strip_says(self, win, f) -> str:
        """What hovering over the wide scope's band-plan strip at `f` shows:
        the segment's tooltip, or '' where the strip is empty."""
        sc = win.wide
        x = sc.fmap.x(f)
        self.assertTrue(0 <= x <= sc.width(), f"{f / 1e6:.3f} MHz is not on the scope")
        QToolTip.hideText()
        QTest.mouseMove(sc, QPoint(int(round(x)), int(sc.r_strip.center().y())))
        self.settle(0.05)
        return QToolTip.text() if QToolTip.isVisible() else ""

    def wait_for_view(self, win, lo, hi):
        """Until the wide scope shows lo..hi (the simulator builds a band's
        stations before the span moves: up to a few seconds)."""
        self.settle(30, until=lambda: win.wide.view_lo <= lo and win.wide.view_hi >= hi)
        self.assertLessEqual(win.wide.view_lo, lo)
        self.assertGreaterEqual(win.wide.view_hi, hi)

    # ------------------------------------------------------------------ the overlay
    def test_the_overlay_draws_the_uk_plan_on_80_40_20_and_2m(self):
        win, bridge, radio = self.window()                  # GM4BRI: the UK, RSGB 2026
        self.assertEqual(radio.state()["planInUse"], plans.rsgb_2026.ID)
        expect = {
            "80m": [(3_530_000, "CW"), (3_575_000, "narrow digital (200 Hz)"), (3_590_000, "narrow digital"),
                    (3_700_000, "all modes")],
            "40m": [(7_020_000, "CW"), (7_045_000, "narrow digital"), (7_150_000, "all modes")],
            "20m": [(14_030_000, "CW"), (14_080_000, "narrow digital"), (14_100_000, "IBP beacons"),
                    (14_118_000, "all modes, no digital"), (14_200_000, "all modes")],
            # 2 m is wider than the simulated Pluto's span: what is around
            # 145.500 FM, where the window starts and so where 2 m was left.
            "2m": [(145_150_000, "repeater inputs"), (145_400_000, "FM simplex"),
                   (145_610_000, "repeater outputs")],
        }
        for name, points in expect.items():
            with self.subTest(band=name):
                self.press(win, name)
                self.assertEqual(radio.state()["band"], name)
                fs = [f for f, _ in points]
                self.wait_for_view(win, min(fs), max(fs))
                for f, label in points:
                    tip = self.strip_says(win, f)
                    self.assertIn(f"<b>{label}</b>", tip, f"{name} at {f / 1e6:.3f} MHz")
        # A reserved segment says so; a segment for transmitting says what for.
        self.assertIn("No transmitting here", self.strip_says(win, 145_610_000))   # a repeater's output
        self.assertIn("FM", self.strip_says(win, 145_400_000))

    def test_the_overlay_follows_the_plan_in_force(self):
        # The same 20 m, with the IARU Region 1 plan chosen: the UK's own
        # "no digital" slot at 14.112-14.125 is not in it.
        win, bridge, radio = self.window(plan=plans.iaru_r1.ID)
        self.assertEqual(radio.state()["planInUse"], plans.iaru_r1.ID)
        self.press(win, "20m")
        self.wait_for_view(win, 14_000_000, 14_350_000)
        self.assertNotIn("no digital", self.strip_says(win, 14_118_000))
        self.assertIn("<b>CW, contest preferred</b>", self.strip_says(win, 14_030_000))

    # ------------------------------------------------------------------ the buttons
    def test_a_first_visit_in_voice_lands_at_the_ssb_segment_in_the_band_s_sideband(self):
        win, bridge, radio = self.window()
        self.assertEqual(radio.state()["mode"], "fm")      # starts on 2 m FM: not a digital mode
        self.press(win, "20m")
        st = radio.state()
        self.assertEqual((st["vfo"], st["mode"]), (14_125_000.0, "usb"))   # RSGB 20 m SSB: 14.125-14.350
        self.press(win, "80m")
        st = radio.state()
        # 80 m all modes from 3.600; LSB, so the dial sits 3 kHz in and the
        # voice is inside the segment rather than in the digital one below.
        self.assertEqual((st["vfo"], st["mode"]), (3_603_000.0, "lsb"))
        self.press(win, "40m")
        st = radio.state()
        self.assertEqual((st["vfo"], st["mode"]), (7_053_000.0, "lsb"))
        self.press(win, "2m")                               # been here: where it was left
        self.assertEqual((radio.state()["vfo"], radio.state()["mode"]), (145_500_000.0, "fm"))

    def test_a_first_visit_in_a_digital_mode_lands_on_the_ft8_dial(self):
        win, bridge, radio = self.window()
        radio.set(mode="psk31")
        self.settle(0.1)
        self.press(win, "40m")
        st = radio.state()
        self.assertEqual((st["vfo"], st["mode"]), (7_074_000.0, "ft8"))
        self.press(win, "20m")                              # still digital (FT8): FT8 again
        self.assertEqual((radio.state()["vfo"], radio.state()["mode"]), (14_074_000.0, "ft8"))
        # FT4 goes to FT4's dial where the band lists one.
        radio.set(mode="ft4")
        self.settle(0.1)
        self.press(win, "17m")
        self.assertEqual((radio.state()["vfo"], radio.state()["mode"]), (18_104_000.0, "ft4"))

    def test_a_first_visit_from_fm_on_2m_and_70cm_lands_on_the_fm_calling_channel(self):
        # Brian, 13/10/2026: an FM operator pressing a VHF/UHF band stays in
        # FM at the RSGB calling channel; anything else is as before.
        win, bridge, radio = self.window()
        self.assertEqual(radio.state()["mode"], "fm")
        self.press(win, "70cm")                             # first visit, from FM
        st = radio.state()
        self.assertEqual((st["vfo"], st["mode"]), (433_500_000.0, "fm"))
        self.assertFalse(radio.state()["keyed"])
        self.assertEqual(radio.dev.tx_written, 0)

    def test_a_first_visit_from_ssb_on_70cm_still_lands_in_the_ssb_segment(self):
        win, bridge, radio = self.window()
        radio.set(mode="usb")
        self.settle(0.1)
        self.press(win, "70cm")
        st = radio.state()
        self.assertEqual(st["mode"], "usb")
        self.assertNotEqual(st["vfo"], 433_500_000.0)

    def test_the_fm_calling_rule_on_2m_by_plan(self):
        # 2 m's first visit is not reachable through the window (the radio
        # starts on 2 m, so leaving it seeds its stack), so judge the rule
        # itself, in the plans that matter.
        b2, b70, b20 = bands.BY_NAME["2m"], bands.BY_NAME["70cm"], bands.BY_NAME["20m"]
        rsgb, r1, r2 = plans.get("rsgb-2026"), plans.get("iaru-r1"), plans.get("iaru-r2")
        for plan in (rsgb, r1):                             # RSGB marks it; the R1 plan needs the constant
            with self.subTest(plan=plan.ID):
                self.assertEqual(bands.first_register(b2, "fm", plan), (145_500_000.0, "fm"))
                self.assertEqual(bands.first_register(b70, "fm", plan), (433_500_000.0, "fm"))
        f, m = bands.first_register(b2, "usb", rsgb)        # from SSB: the SSB segment as before
        self.assertEqual(m, "usb")
        self.assertNotEqual(f, 145_500_000.0)
        self.assertEqual(bands.first_register(b2, "fm", r2)[1], "usb")     # R2 calls elsewhere: no guess
        self.assertEqual(bands.first_register(b20, "fm", rsgb)[1], "usb")  # HF: unchanged
        self.assertEqual(bands.seed_stack(b2, "fm", rsgb)[0], {"vfo": 145_500_000.0, "mode": "fm"})

    def test_a_band_remembers_where_it_was_left(self):
        win, bridge, radio = self.window()
        self.press(win, "20m")
        radio.set(vfo=14_210_500.0, mode="usb")
        self.settle(0.1)
        self.press(win, "80m")
        radio.set(vfo=3_712_000.0, mode="lsb")
        self.settle(0.1)
        self.press(win, "20m")
        self.assertEqual((radio.state()["vfo"], radio.state()["mode"]), (14_210_500.0, "usb"))
        self.press(win, "80m")
        self.assertEqual((radio.state()["vfo"], radio.state()["mode"]), (3_712_000.0, "lsb"))
        # A second press on the band in use steps to its next register: the
        # band's FT8 dial, then CW.
        self.press(win, "80m")
        self.assertEqual((radio.state()["vfo"], radio.state()["mode"]), (3_573_000.0, "ft8"))
        self.press(win, "80m")
        self.assertEqual(radio.state()["mode"], "cw")
        # None of it keyed anything.
        self.assertFalse(radio.state()["keyed"])
        self.assertEqual(radio.dev.tx_written, 0)

    # ------------------------------------------------------------------ coverage
    def test_the_row_holds_only_the_bands_the_receiver_covers(self):
        win, bridge, radio = self.window()
        # The simulator covers 160 m to 6 cm; 6 m has no radio here at all.
        self.assertEqual(self.on_row(win), [b.name for b in bands.BANDS if b.name != "6m"])
        # A receiver that stops at 38.4 MHz (a Hermes-Lite 2): HF only.
        radio.dev.rx_range = (0.0, 38.4e6)
        self.assertEqual(self.on_row(win), ["160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"])
        # A Pluto seen as an AD9363 (325 MHz-3.8 GHz) keeps 4 m and 2 m on
        # the row, faint: one setting reaches them, and clicking says so.
        radio.dev.rx_range = (325e6, 3.8e9)
        radio.dev.kind, radio.dev.identity = "pluto", "ad9363"
        # So does 6 cm, above the AD9363's 3.8 GHz; HF, which no Pluto
        # reaches, does not.
        self.assertEqual(self.on_row(win), ["4m", "2m", "70cm", "23cm", "13cm", "9cm", "6cm"])
        self.assertEqual(win.bandbar._status(bands.BY_NAME["2m"])[0], "off")


if __name__ == "__main__":
    unittest.main()
