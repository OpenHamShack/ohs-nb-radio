"""The S-meter (ohscore/ui/smeter.py): IARU R1's S-units and the HF/VHF
boundary, typed levels, the calibration arithmetic and when it may be called
calibrated, the passband noise reference, and the widget itself driven as an
operator would - clicks on the reading and the meter, Settings - on Qt's
offscreen platform. Nothing here reads source text."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import math
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


def st(**over):
    d = {"device": "pluto", "plutoUri": "ip:192.168.2.1", "rxGainMode": "manual", "rxGain": 40.0,
         "vfo": 10_489_750_000.0}
    d.update(over)
    return d


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Standard(unittest.TestCase):
    def test_s9_is_minus_73_dbm_below_30_mhz_and_minus_93_from_there_up(self):
        from ohscore.ui.smeter import s9_dbm
        self.assertEqual(s9_dbm(1_840_000), -73.0)
        self.assertEqual(s9_dbm(14_200_000), -73.0)
        self.assertEqual(s9_dbm(29_999_999), -73.0)
        self.assertEqual(s9_dbm(30_000_000), -93.0)
        self.assertEqual(s9_dbm(50_200_000), -93.0)
        self.assertEqual(s9_dbm(145_500_000), -93.0)
        self.assertEqual(s9_dbm(10_489_750_000), -93.0)      # NB's downlink: VHF and up

    def test_s_unit_text(self):
        from ohscore.ui.smeter import s_text
        hf = -73.0
        cases = {-73.0: "S9", -79.0: "S8", -85.0: "S7", -121.0: "S1", -127.0: "S0", -150.0: "S0",
                 -63.0: "S9+10", -53.0: "S9+20", -33.0: "S9+40", -72.6: "S9", -72.4: "S9+1", -75.9: "S9",
                 -76.1: "S8"}
        for dbm, want in cases.items():
            self.assertEqual(s_text(dbm, hf), want, dbm)
        self.assertEqual(s_text(-93.0, -93.0), "S9")
        self.assertEqual(s_text(-73.0, -93.0), "S9+20")     # an HF S9 is S9+20 on 2 m

    def test_s_beacon_ref_puts_the_beacon_at_s9_with_no_calibration(self):
        from ohscore.ui.smeter import CalState, reading, scale_for
        uncal = CalState(0.0, False, "")
        for passband, want in ((-60.0, "S9"), (-72.0, "S7"), (-40.0, "S9+20"), (-114.0, "S0")):
            r = reading("sbeacon", passband, -93.0, uncal, beacon=-60.0)
            self.assertEqual(r.text, want, passband)
            self.assertFalse(r.uncal)                         # the beacon is the reference: nothing to calibrate
            self.assertEqual(r.value, passband + 60.0)
        self.assertIn("-12.0 dB vs beacon", reading("sbeacon", -72.0, -93.0, uncal, beacon=-60.0).second)
        self.assertIsNone(reading("sbeacon", -72.0, -93.0, uncal, beacon=None).value)
        self.assertIsNone(reading("sbeacon", -72.0, -93.0, uncal, beacon=-200.0).value)
        # S9 sits where it does on the S scale: 60 % along.
        sc = scale_for("sbeacon", -93.0)
        self.assertAlmostEqual(sc.pos(0.0), 0.6)
        self.assertAlmostEqual(sc.pos(-54.0), 0.0)
        self.assertAlmostEqual(sc.pos(40.0), 1.0)

    def test_typed_levels(self):
        from ohscore.ui.smeter import parse_level
        self.assertEqual(parse_level("-73", -73.0), -73.0)
        self.assertEqual(parse_level(" -101.5 dBm ", -93.0), -101.5)
        self.assertEqual(parse_level("−80", -93.0), -80.0)          # a typographic minus
        self.assertEqual(parse_level("S9", -73.0), -73.0)
        self.assertEqual(parse_level("s7", -73.0), -85.0)
        self.assertEqual(parse_level("S9+20", -93.0), -73.0)
        self.assertEqual(parse_level("S9+10dB", -73.0), -63.0)
        self.assertAlmostEqual(parse_level("50 uV", -73.0), -73.0, delta=0.05)   # the recommendation's own pair
        self.assertAlmostEqual(parse_level("5µV", -93.0), -93.0, delta=0.05)
        for bad in ("loud", "S7+10", "0 uV", "-500", ""):
            with self.assertRaises(ValueError):
                parse_level(bad, -73.0)

    def test_needle_angles(self):
        from ohscore.ui.smeter import HALF_SWEEP, needle_angle, scale_for
        sc = scale_for("s", -93.0)
        self.assertAlmostEqual(needle_angle(sc.pos(-93.0 - 54)), -HALF_SWEEP)   # S0: full left
        self.assertAlmostEqual(needle_angle(sc.pos(-93.0)), -HALF_SWEEP + 2 * HALF_SWEEP * 0.6)   # S9 at 60 %
        self.assertAlmostEqual(needle_angle(sc.pos(-93.0 + 60)), HALF_SWEEP)   # S9+60: full right
        self.assertAlmostEqual(needle_angle(sc.pos(0.0)), HALF_SWEEP)          # pinned, never past the stop
        # One S-unit is the same swing everywhere below S9.
        a = [needle_angle(sc.pos(-93.0 - 6 * k)) for k in range(9)]
        steps = np.diff(a)
        self.assertTrue(np.allclose(steps, steps[0]))
        # Linear units: the middle of the range is upright.
        self.assertAlmostEqual(needle_angle(scale_for("dbfs", -93.0).pos(-80.0)), 0.0)

    def test_passband_noise_matches_the_meter_on_white_noise(self):
        # The noise reference converts the zoom spectrum's median per bin to
        # the power a passband would hold; on pure noise it must agree with
        # what the passband meter measures, whatever the averaging.
        from ohscore.dsp.spectrum import Scope
        from ohscore.ui.smeter import passband_noise_dbfs
        rate, sigma2, bw = 12_000, 1e-6, 2400.0
        rng = np.random.default_rng(3)
        x = (rng.standard_normal(rate * 20) + 1j * rng.standard_normal(rate * 20)) * math.sqrt(sigma2 / 2)
        truth = 10 * math.log10(sigma2 * bw / rate)
        for avg in (1, 2, 4):
            sc = Scope(rate, 1024, 10.0, avg)
            lines = sc.process(x.astype(np.complex64))
            meds = [float(np.median(db)) for _, db in lines]
            est = passband_noise_dbfs(float(np.median(meds)), sc.bin_hz, bw, avg)
            self.assertAlmostEqual(est, truth, delta=0.6, msg=f"avg {avg}")


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Calibration(unittest.TestCase):
    def test_offset_is_what_makes_the_reading_the_known_level(self):
        from ohscore.ui.smeter import calibrate, effective
        store = calibrate({}, st(), -100.0, -73.0, when="2026-10-05")
        c = effective(store, st())
        self.assertTrue(c.ok)
        self.assertAlmostEqual(-100.0 + c.offset, -73.0)

    def test_a_manual_gain_change_is_allowed_for(self):
        from ohscore.ui.smeter import calibrate, effective
        store = calibrate({}, st(rxGain=40.0), -100.0, -73.0)
        # Ten dB more gain: the same signal reads ten dB higher in dBFS, and
        # must still come out at -73 dBm.
        c = effective(store, st(rxGain=50.0))
        self.assertTrue(c.ok)
        self.assertAlmostEqual(-90.0 + c.offset, -73.0)
        self.assertIn("50 dB", c.why)

    def test_the_receivers_own_agc_means_it_does_not_hold(self):
        from ohscore.ui.smeter import calibrate, effective
        store = calibrate({}, st(), -100.0, -73.0)
        c = effective(store, st(rxGainMode="slow_attack"))
        self.assertFalse(c.ok)
        self.assertIn("AGC", c.why)
        with self.assertRaises(ValueError):
            calibrate({}, st(rxGainMode="fast_attack"), -100.0, -73.0)

    def test_the_simulator_and_the_hl2_know_their_gain(self):
        from ohscore.ui.smeter import calibrate, effective, known_gain
        self.assertEqual(known_gain(st(device="sim", rxGainMode="slow_attack")), 40.0)
        self.assertEqual(known_gain(st(device="hl2", rxGainMode="slow_attack", hl2Lna=12.0)), 12.0)
        store = calibrate({}, st(device="hl2", hl2Lna=20.0, band="20m"), -90.0, -73.0)
        self.assertTrue(effective(store, st(device="hl2", hl2Lna=20.0, band="20m")).ok)

    def test_per_radio_and_per_band(self):
        from ohscore.ui.smeter import calibrate, effective
        store = calibrate({}, st(band="2m"), -100.0, -93.0)
        self.assertTrue(effective(store, st(band="2m")).ok)
        self.assertFalse(effective(store, st(band="70cm")).ok)
        self.assertFalse(effective(store, st(band="2m", plutoUri="ip:192.0.2.74")).ok)
        between = effective(store, st(band=""))
        self.assertFalse(between.ok)
        self.assertIn("between bands", between.why)
        with self.assertRaises(ValueError):
            calibrate(store, st(band=""), -100.0, -93.0)

    def test_refuses_a_clipping_or_missing_reading(self):
        from ohscore.ui.smeter import calibrate
        for bad in (-1.0, None, -200.0):
            with self.assertRaises(ValueError):
                calibrate({}, st(), bad, -73.0)

    def test_forget_and_a_hand_edited_store(self):
        from ohscore.ui.smeter import calibrate, clean_cal, effective, forget
        store = calibrate({}, st(), -100.0, -73.0)
        self.assertFalse(effective(forget(store, st()), st()).ok)
        junk = {"a": {"offset": "x", "gain": 1}, "b": 5, "c": {"offset": float("nan"), "gain": 0},
                "d": {"offset": 12, "gain": 40}}
        self.assertEqual(list(clean_cal(junk)), ["d"])
        self.assertEqual(clean_cal("nonsense"), {})


class FakeFace:
    def __init__(self, beacon):
        self.smeter_beacon = beacon


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Widget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._hook = sys.excepthook
        self.errors = []
        sys.excepthook = lambda t, v, tb: self.errors.append((t, v, tb))

    def tearDown(self):
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.errors:
            self.fail(f"exceptions in Qt slots: {self.errors}")

    def meter(self, beacon=True, **stover):
        from ohscore.ui.prefs import Prefs
        from ohscore.ui.smeter import SMeter
        prefs = Prefs(os.path.join(self.tmp, "ui.json"))
        bridge = SimpleNamespace(st=st(**stover), face=FakeFace(beacon))
        m = SMeter(bridge, prefs)
        m.resize(252, m.height())
        m.show()
        return m, prefs, bridge

    def settle(self, m, secs=2.0):
        for _ in range(int(secs * 30)):
            m.tick(1 / 30)

    def test_default_is_todays_dbfs_bar(self):
        m, _p, _b = self.meter()
        self.assertEqual(m.style, "bar")
        self.assertEqual(m.unit, "dbfs")
        self.assertEqual(m.height(), 50)
        m.feed(-87.34)
        self.assertEqual(m.value_text(), "-87.3 dBFS")
        self.assertEqual([m.tick_label(t) for t in m.ticks], ["-130", "-110", "-90", "-70", "-50", "-30"])
        m.feed(None)
        self.assertEqual(m.value_text(), "—")

    def test_click_on_the_reading_cycles_units_and_it_persists(self):
        from ohscore.ui.prefs import Prefs
        m, prefs, _b = self.meter(beacon=True)
        m.feed(-90.0, beacon=-80.0)
        m.set_noise(-110.0)
        seen = []
        for _ in range(6):
            QTest.mouseClick(m, Qt.MouseButton.LeftButton, pos=m.unit_rect().center().toPoint())
            seen.append(m.unit)
        self.assertEqual(seen, ["snr", "beacon", "sbeacon", "s", "dbm", "dbfs"])
        self.assertEqual(m.style, "bar")                       # the unit click never changes the style
        QTest.mouseClick(m, Qt.MouseButton.LeftButton, pos=m.unit_rect().center().toPoint())
        self.assertEqual(Prefs(os.path.join(self.tmp, "ui.json"))["sMeterUnit"], "snr")
        self.assertEqual(m.value_text(), "20 dB over noise")
        QTest.mouseClick(m, Qt.MouseButton.LeftButton, pos=m.unit_rect().center().toPoint())
        self.assertEqual(m.value_text(), "-10.0 dB vs beacon")

    def test_no_beacon_unit_without_a_beacon(self):
        m, _p, _b = self.meter(beacon=False)
        seen = []
        for _ in range(4):
            QTest.mouseClick(m, Qt.MouseButton.LeftButton, pos=m.unit_rect().center().toPoint())
            seen.append(m.unit)
        self.assertEqual(seen, ["snr", "s", "dbm", "dbfs"])
        m.prefs["sMeterUnit"] = "beacon"                       # an NB ui.json opened by HAM
        m.apply_prefs()
        self.assertEqual(m.unit, "dbfs")

    def test_click_elsewhere_cycles_styles(self):
        m, prefs, _b = self.meter()
        heights = []
        for _ in range(3):
            QTest.mouseClick(m, Qt.MouseButton.LeftButton, pos=QPoint(20, m.height() - 6))
            heights.append((m.style, m.height()))
        self.assertEqual([s for s, _ in heights], ["analog", "digital", "bar"])
        self.assertEqual(heights[0][1], m.HEIGHTS["analog"])
        self.assertEqual(heights[2][1], 50)
        self.assertEqual(prefs["sMeterUnit"], "")              # never chosen: the app's default

    def test_uncal_until_calibrated(self):
        from ohscore.ui.smeter import calibrate
        m, prefs, b = self.meter(device="pluto", vfo=145_500_000.0)
        prefs["sMeterUnit"] = "s"
        m.apply_prefs()
        m.feed(-60.0)
        self.assertTrue(m.rd.uncal)
        self.assertIn("Uncalibrated", m.toolTip())
        self.assertIn("Calibrate", m.toolTip())
        m.set_pref("sMeterCal", calibrate({}, b.st, -60.0, -93.0))
        m.feed(-60.0)
        self.assertFalse(m.rd.uncal)
        self.assertEqual(m.value_text(), "S9")
        m.feed(-40.0)
        self.assertEqual(m.value_text(), "S9+20")
        prefs["sMeterUnit"] = "dbm"
        m.apply_prefs()
        self.assertEqual(m.value_text(), "-73.0 dBm")
        # The radio's own AGC switched on: the same figure is UNCAL again.
        b.st["rxGainMode"] = "slow_attack"
        m.feed(-40.0)
        self.assertTrue(m.rd.uncal)
        self.assertIn("AGC", m.toolTip())

    def test_uncalibrated_never_shows_an_absolute_figure(self):
        # A Pluto behind a QO-100 LNB: -21 dBFS used to read S9+72.
        for unit in ("s", "dbm"):
            for style in ("bar", "analog", "digital"):
                m, prefs, _b = self.meter(device="pluto", vfo=10_489.5e6)
                prefs["sMeterStyle"], prefs["sMeterUnit"] = style, unit
                m.apply_prefs()
                m.feed(-21.0)
                self.assertTrue(m.rd.uncal)
                self.assertEqual(m.value_text(), "-21.0 dBFS")          # no noise floor yet
                m.set_noise(-60.0)
                m.feed(-21.0)
                self.assertEqual(m.value_text(), "39 dB over noise")
                for txt in (m.value_text(), m.rd.text, m.rd.second):
                    self.assertNotIn("S9", txt)
                    self.assertNotIn("dBm", txt)
                m.grab()                                               # paints without error

    def test_nb_defaults_to_the_beacon_and_a_stored_choice_wins(self):
        from ohsnb.ui.face import Qo100Face
        from ohscore.ui.face import Face
        self.assertEqual(Qo100Face.smeter_default_unit, "sbeacon")
        self.assertEqual(Face.smeter_default_unit, "dbfs")
        from ohscore.ui.prefs import Prefs
        from ohscore.ui.smeter import SMeter
        prefs = Prefs(os.path.join(self.tmp, "ui.json"))
        m = SMeter(SimpleNamespace(st=st(), face=Qo100Face()), prefs)
        self.assertEqual(m.unit, "sbeacon")
        m.feed(-90.0, beacon=-80.0)
        self.assertEqual(m.value_text(), "S7")
        m.set_pref("sMeterUnit", "beacon")                     # a choice made before the default moved is kept
        self.assertEqual(SMeter(SimpleNamespace(st=st(), face=Qo100Face()),
                                Prefs(os.path.join(self.tmp, "ui.json"))).unit, "beacon")
        m.set_pref("sMeterUnit", "dbfs")                       # the operator's choice, even the old default
        self.assertEqual(SMeter(SimpleNamespace(st=st(), face=Qo100Face()),
                                Prefs(os.path.join(self.tmp, "ui.json"))).unit, "dbfs")
        # Radio keeps dBFS.
        self.assertEqual(SMeter(SimpleNamespace(st=st(), face=FakeFace(False)), Prefs(os.path.join(self.tmp, "x.json"))).unit,
                         "dbfs")

    def test_hf_and_vhf_read_the_same_dbm_differently(self):
        from ohscore.ui.smeter import calibrate
        m, prefs, b = self.meter(beacon=False, device="sim", band="20m", vfo=14_200_000.0)
        prefs["sMeterUnit"] = "s"
        m.set_pref("sMeterCal", calibrate({}, b.st, -100.0, -73.0))
        m.feed(-100.0)
        self.assertEqual(m.value_text(), "S9")
        b.st.update(band="2m", vfo=145_500_000.0)
        prefs["sMeterCal"] = calibrate(prefs["sMeterCal"], b.st, -100.0, -73.0)
        m.feed(-100.0)
        self.assertEqual(m.value_text(), "S9+20")

    def test_analog_needle_follows_with_ballistics(self):
        from ohscore.ui.smeter import calibrate, needle_angle
        m, prefs, b = self.meter(beacon=False, device="sim", vfo=145_500_000.0)
        prefs["sMeterStyle"], prefs["sMeterUnit"] = "analog", "s"
        prefs["sMeterCal"] = calibrate({}, b.st, -100.0, -93.0)
        m.apply_prefs()
        m.feed(-100.0)                                         # S9
        m.tick(1 / 30)
        self.assertAlmostEqual(needle_angle(m.b.value), needle_angle(0.6), delta=0.5)   # attack: at once
        m.feed(-154.0)                                         # S0
        for _ in range(15):                                    # half a second of 30 Hz frames
            m.tick(1 / 30)
        # Decay time constant 0.5 s: after 0.5 s about 1/e of the swing remains.
        left = (m.b.value - 0.0) / 0.6
        self.assertGreater(left, 0.2)
        self.assertLess(left, 0.5)
        self.assertGreater(m.b.peak, m.b.value)               # the peak needle holds
        self.settle(m, 4.0)
        self.assertAlmostEqual(needle_angle(m.b.value), needle_angle(0.0), delta=0.5)

    def test_every_style_paints_in_both_themes_and_the_dial_is_cached(self):
        from ohscore.ui import theme
        m, prefs, _b = self.meter()
        m.feed(-80.0, beacon=-70.0)
        m.set_noise(-100.0)
        try:
            for name in ("dark", "light"):
                theme.set_theme(name)
                for style in ("bar", "analog", "digital"):
                    for unit in ("s", "dbm", "dbfs", "snr", "beacon", "sbeacon"):
                        prefs["sMeterStyle"], prefs["sMeterUnit"] = style, unit
                        m.apply_prefs()
                        self.settle(m, 0.3)
                        self.assertFalse(m.grab().isNull())
            prefs["sMeterStyle"] = "analog"
            m.apply_prefs()
            m.grab()
            face = m._face[1]
            for v in (-90.0, -70.0, -60.0):                   # the needle moves, the face is not redrawn
                m.feed(v)
                m.tick(0.1)
                m.grab()
            self.assertIs(m._face[1], face)
            m.resize(300, m.height())
            m.grab()
            self.assertIsNot(m._face[1], face)
        finally:
            theme.set_theme("dark")

    def test_the_needle_never_crosses_the_legend(self):
        # 0.1.3: the legend sat mid-face and every mid-scale reading drew the
        # needle through it. Checked on the painted pixels: whatever the
        # reading, and with the peak needle out too, the legend's pixels
        # are the same.
        from ohscore.ui.smeter import calibrate
        for w in (252, 376):
            for unit, cal in (("s", True), ("s", False), ("dbm", True), ("snr", False), ("dbfs", False)):
                m, prefs, b = self.meter(beacon=False, device="sim", vfo=145_500_000.0)
                prefs["sMeterStyle"], prefs["sMeterUnit"] = "analog", unit
                prefs["sMeterCal"] = calibrate({}, b.st, -100.0, -93.0) if cal else {}
                m.apply_prefs()
                m.resize(w, m.height())
                m.feed(-100.0)
                m.set_noise(-110.0)
                self.settle(m, 0.5)
                boxes = [box for box, *_ in m.legend_layout(m.width(), m.height())]
                texts = [t for _b, t, *_ in m.legend_layout(m.width(), m.height())]
                self.assertTrue(texts, (w, unit))
                if unit in ("s", "dbm") and cal:        # uncalibrated shows the relative scale, no S9 legend
                    self.assertTrue(any(t.startswith("S9 -93 dBm") for t in texts), (w, unit, texts))
                seen = None
                for pos in [i / 40 for i in range(41)]:
                    m.b.value, m.b.peak = pos, min(1.0, pos + 0.2)
                    img = m.grab().toImage()
                    px = [img.pixel(x, y) for r in boxes
                          for x in range(int(r.left()), int(r.right()) + 1)
                          for y in range(int(r.top()), int(r.bottom()) + 1)]
                    if seen is None:
                        seen = px
                    self.assertEqual(px, seen, f"the needle crossed the legend at {pos:.3f} ({w} px, {unit})")
                m.close()

    def test_transmit_meters_are_unchanged(self):
        from ohscore.ui.meters import BarMeter
        b = BarMeter("Power", -60, 0, lambda v: f"{v:.0f}", ticks=(-60, -30, 0), unit="dB")
        b.set_value(-12.4)
        b.tick(0.1)
        self.assertEqual(b.value_text(), "-12 dB")
        self.assertEqual([b.tick_label(t) for t in b.ticks], ["-60", "-30", "0"])
        self.assertFalse(b.grab().isNull())


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class InTheWindow(unittest.TestCase):
    """The meter on the rail of the real NB window, and Settings › Radio."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_s_beacon_ref_does_not_move_with_the_agc(self):
        # Both levels come from the receive IQ ahead of the AGC (the
        # passband in demod, the beacon in beacon lock), so changing the
        # AGC moves neither. On the simulator's middle beacon itself, which
        # is steady, so the reading is S9 give or take its own fades.
        import time
        from helpers import make_radio
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        radio = make_radio(self.tmp, mode="usb", vfo=10_489_748_500.0, agc="fast")
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        win, bridge = build(radio, prefs)
        try:
            win.show()
            m = win.rxcard.s
            self.assertEqual(m.unit, "sbeacon")                # NB's default with nothing stored

            def mean_reading(secs):
                vals, t0 = [], time.monotonic()
                while time.monotonic() - t0 < secs:
                    self.app.processEvents()
                    if m.rd.value is not None:
                        vals.append(m.rd.value)
                    time.sleep(0.01)
                return sum(vals) / len(vals) if vals else None

            t0 = time.monotonic()
            while (m.beacon is None or m.beacon <= -199) and time.monotonic() - t0 < 60:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIsNotNone(m.beacon, "beacon lock never measured the beacon")
            mean_reading(1.0)
            fast = mean_reading(3.0)
            bridge.set(agc="off")
            mean_reading(1.0)
            off = mean_reading(3.0)
            bridge.set(agc="slow")
            mean_reading(1.0)
            slow = mean_reading(3.0)
            self.assertIsNotNone(fast)
            self.assertAlmostEqual(fast, 0.0, delta=4.0)       # the beacon in the passband: about S9
            self.assertAlmostEqual(off, fast, delta=1.5)
            self.assertAlmostEqual(slow, fast, delta=1.5)
        finally:
            win.close()
            bridge.stop()
            self.app.processEvents()

    def test_feeds_reach_it_and_settings_change_it(self):
        import time
        from helpers import make_radio
        from ohscore.ui.prefs import Prefs
        from ohscore.ui.smeter import SMeter
        from ohsnb import config
        from ohsnb.ui import build
        radio = make_radio(self.tmp, rxGainMode="manual")
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        win, bridge = build(radio, prefs)
        try:
            win.resize(1366, 768)
            win.show()
            m = win.rxcard.s
            self.assertIsInstance(m, SMeter)
            t0 = time.monotonic()
            while (m.dbfs is None or m.noise is None) and time.monotonic() - t0 < 30:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIsNotNone(m.dbfs)
            self.assertIsNotNone(m.noise)
            self.assertTrue(m.dbfs - m.noise > -6.0)           # the passband holds at least its own noise
            d = win.settings_dialog()
            w = d._smeter
            w["style"].set_value("analog")
            w["unit"].set_value("dbm")
            w["offset"].setText("-20")
            d.save()
            self.assertEqual(prefs["sMeterStyle"], "analog")
            win.apply_prefs(False)
            self.assertEqual(m.style, "analog")
            self.assertEqual(m.height(), m.HEIGHTS["analog"])
            m.feed(-80.0)
            self.assertFalse(m.rd.uncal)                       # the simulator knows its gain
            self.assertEqual(m.value_text(), "-100.0 dBm")
            # A nonsense offset is refused with a sentence, and nothing saved.
            d = win.settings_dialog()
            d._smeter["offset"].setText("loud")
            d.save()
            self.assertTrue(d.error.isVisibleTo(d))
            self.assertIn("not a number", d.error.text())
            d.reject()
        finally:
            win.close()
            bridge.stop()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
