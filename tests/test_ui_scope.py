"""The scope widget on its own, fed spectrum lines directly: what the
operator's settings do to the scale, the waterfall's levels, the peak ghost,
the averaging and the peak markers. A small stand-in bridge carries the
three signals and the state the scope reads, so each test decides exactly
what the scope sees - real noise statistics from ohscore.dsp.spectrum, not
hand-made arrays - and checks what the scope then does with it."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

DIAL = 10_489_600_000.0

if HAVE_QT:
    class StubBridge(QObject):
        """What ScopeView asks of the real Bridge, and nothing else."""
        wide = pyqtSignal(list)
        zoom = pyqtSignal(list)
        changed = pyqtSignal(dict)

        def __init__(self, face=None):
            super().__init__()
            from ohsnb.ui.face import Qo100Face
            self.face = face if face is not None else Qo100Face()
            self.st = {"vfo": DIAL, "rxDial": DIAL, "zoomSpanHz": 12000.0, "zoomPan": 0.0, "mode": "usb",
                       "running": True}

        def spec(self, k):
            return {"min": 1000.0, "max": 50000.0}

        def set(self, quiet=False, **kw):
            self.st.update(kw)


def noise_lines(scope, n, snr_db=None, f_sig=None, seed=1, t0=0.0, dt=0.05, avg=2):
    """n spectrum lines across `scope`'s view as the engine makes them
    (Hann-windowed, `avg` FFTs averaged), of white noise plus, optionally, a
    carrier `snr_db` above the noise in one bin at `f_sig`."""
    from ohscore.dsp.spectrum import Scope
    rng = np.random.default_rng(seed)
    lo, hi = scope.fmap.lo, scope.fmap.hi
    nfft = 1024
    rate = (hi - lo) * 1.1
    bin_hz = rate / nfft
    start = (lo + hi) / 2 - nfft // 2 * bin_hz
    sc = Scope(rate, nfft, 1.0 / dt, avg)
    per = int(rate * dt)
    out, t, k = [], t0, 0
    while len(out) < n:
        x = (rng.standard_normal(per) + 1j * rng.standard_normal(per)) * 1e-3
        if snr_db is not None:
            # Per-bin noise power is 2e-6 / nfft of the total; a tone of
            # amplitude a puts a**2 into its bin.
            a = np.sqrt(2e-6 * 10 ** (snr_db / 10) * 1.5 / nfft) * np.sqrt(nfft)
            tt = (np.arange(per) + k * per) / rate
            x = x + a * np.exp(2j * np.pi * (f_sig - (lo + hi) / 2) * tt)
        k += 1
        for _end, db in sc.process(x.astype(np.complex64)):
            t += dt
            out.append((t, start, bin_hz, db))
    return out[:n]


def carrier_lines(scope, n, carrier_db=None, f_sig=None, t0=0.0, dt=0.05, floor_db=-100.0, more=(), jitter=0.0,
                  seed=3):
    """n lines of a flat floor, optionally with carriers - `carrier_db` at
    `f_sig` and any (Hz, dB) in `more` - and optionally `jitter` dB of
    random wobble on every bin: for the parts whose arithmetic is easier to
    check without real noise."""
    lo, hi = scope.fmap.lo, scope.fmap.hi
    nb = 1024
    bin_hz = (hi - lo) / nb
    rng = np.random.default_rng(seed)
    sigs = list(more) + ([(f_sig, carrier_db)] if carrier_db is not None else [])
    out = []
    for i in range(n):
        db = np.full(nb, floor_db, np.float32)
        for f, level in sigs:
            db[int((f - lo) / bin_hz)] = level
        if jitter:
            db += rng.uniform(-jitter, jitter, nb).astype(np.float32)
        out.append((t0 + (i + 1) * dt, lo + bin_hz / 2, bin_hz, db))
    return out


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class ScopeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.views = []

    def tearDown(self):
        for v in self.views:
            v.close()
            v.deleteLater()
        self.app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scope(self, kind="zoom", face=None, size=(1000, 420), prefs=None):
        from ohscore.ui.prefs import Prefs
        from ohscore.ui.scope import ScopeView
        self.prefs = prefs if prefs is not None else Prefs(os.path.join(self.tmp, "ui.json"))
        self.bridge = StubBridge(face)
        v = ScopeView(self.bridge, self.prefs, kind)
        v.resize(*size)
        v.show()
        self.app.processEvents()
        self.views.append(v)
        return v

    def feed(self, v, lines):
        for line in lines:
            v.on_lines([line])

    def adjust(self, v):
        """Open the scope's adjust panel the way the operator does: a click
        on the button in the waterfall's corner."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         v._levels_button().center().toPoint())
        pop = next(w for w in QApplication.topLevelWidgets()
                   if type(w).__name__ == "AdjustPopover" and w.isVisible() and w.scope is v)
        self.addCleanup(pop.close)
        return pop


class AxisCaption(ScopeCase):
    def test_the_caption_is_never_narrower_than_its_text(self):
        from PyQt6.QtGui import QFontMetricsF
        from ohsnb.ui.face import Qo100Face

        class Wordy(Qo100Face):
            axis_unit = "kHz above 10489 MHz downlink"     # far wider than the old fixed 64 px

        for face in (Qo100Face(), Wordy()):
            for kind in ("wide", "zoom"):
                v = self.scope(kind, face=face)
                cap = v._axis_caption_rect()
                text_w = QFontMetricsF(v._axis_caption_font()).horizontalAdvance(face.axis_unit)
                self.assertGreaterEqual(cap.width(), text_w, (kind, face.axis_unit))
                labels = v._axis_labels()
                self.assertTrue(labels, kind)                     # the axis still has labels
                for _x, box, lab in labels:
                    self.assertGreater(box.left(), cap.right(), (kind, lab))   # none over the caption
                    self.assertLessEqual(box.right(), v.width())


class WaterfallLevels(ScopeCase):
    def test_a_flat_noise_spectrum_is_not_drawn_black(self):
        """Ray's zoom waterfall on the real downlink: nothing but noise and
        one weak signal, and the automatic floor sat above most of the noise,
        so most of the waterfall was the palette's floor colour."""
        for kind in ("zoom", "wide"):
            v = self.scope(kind)
            f_sig = (v.fmap.lo + v.fmap.hi) / 2 + 0.2 * v.fmap.span
            self.feed(v, noise_lines(v, 200, snr_db=3.0, f_sig=f_sig))
            rows = v.wf.ordered()[:100]
            black = rows == v.wf.lut[0]
            self.assertLess(float(black.mean()), 0.25, kind)       # was 0.80 with the floor 5 dB up
            self.assertGreater(float(black.mean()), 0.0, kind)     # and noise is still dim, not a field of colour
            # The weak signal's column is lit far more often than the noise around it.
            x = int(v.fmap.x(f_sig) * v.wf.w / v.width())
            lit_sig = float((~black[:, x - 1:x + 2]).any(axis=1).mean())
            self.assertGreater(lit_sig, 0.95, kind)

    def test_a_retune_leaves_no_black_block_in_the_zoom_waterfall(self):
        """0.1.3 SSTV and FreeDV screenshots: after a retune further than
        the zoom's span, everything under the new rows was the palette's
        floor colour - black - until it scrolled away. Nothing there has
        history, but it should read as quiet band, not as a hole."""
        v = self.scope("zoom")
        self.feed(v, noise_lines(v, v.wf.h + 20))

        def brightness(px):
            return ((px >> 16) & 255) + ((px >> 8) & 255) + (px & 255)

        noise = brightness(v.wf.ordered()[:50]).astype(float)
        self.bridge.st["rxDial"] = DIAL + 40_000.0              # three spans away: no column keeps history
        v._on_state({"rxDial": DIAL + 40_000.0})
        self.feed(v, noise_lines(v, 20, seed=5, t0=100.0))
        vacated = v.wf.ordered()[40:]
        self.assertLess(float((vacated == v.wf.lut[0]).mean()), 0.5)
        b = brightness(vacated).astype(float)
        # As bright as the middle of the noise, not as its darkest.
        self.assertGreater(b.mean(), np.percentile(noise, 30))
        self.assertLess(b.mean(), np.percentile(noise, 70))
        # A small retune still keeps the history that is still in view.
        before = v.wf.ordered()[0].copy()
        self.bridge.st["rxDial"] = DIAL + 40_000.0 + v.fmap.span / 4
        v._on_state({"rxDial": self.bridge.st["rxDial"]})
        after = v.wf.ordered()[0]
        q = v.wf.w // 4
        self.assertGreater(float((after[:v.wf.w - q] == before[q:]).mean()), 0.99)

    def test_manual_starts_from_the_automatic_levels(self):
        v = self.scope("zoom")
        self.feed(v, noise_lines(v, 60))
        auto = v.auto_levels()
        self.assertEqual(v._wf_levels(), auto)
        self.prefs["zoomWfAuto"] = False
        self.prefs["zoomWfFloor"], self.prefs["zoomWfRange"] = -100.0, 40.0
        self.assertEqual(v._wf_levels(), (-100.0, 40.0))


class ScopeScale(ScopeCase):
    def test_manual_scale_starts_where_auto_was_and_the_grid_follows(self):
        v = self.scope("zoom")
        self.feed(v, noise_lines(v, 80))
        v.repaint()
        top, rng = v.auto_scale()
        self.assertEqual((v.db_hi, v.db_hi - v.db_lo), (top, rng))
        pop = self.adjust(v)
        pop.spec_auto.set_on(False, emit=True)
        self.assertFalse(self.prefs["zoomSpecAuto"])
        self.assertEqual((self.prefs["zoomSpecTop"], self.prefs["zoomSpecRange"]), (top, rng))
        v.repaint()
        self.assertEqual((v.db_hi, v.db_hi - v.db_lo), (top, rng))       # nothing jumped
        self.assertTrue(self.prefs["specAuto"])                          # the wide scope's own is untouched

        pop.spec_top.set_value(-20, emit=True)
        pop.spec_range.set_value(30, emit=True)
        v.repaint()
        self.assertEqual((v.db_lo, v.db_hi), (-50.0, -20.0))
        grid = v.db_grid()
        self.assertEqual(grid[0][0], -20.0)                              # the top line is the new top
        self.assertAlmostEqual(grid[0][1], v.y_db(-20.0), delta=0.6)
        self.assertTrue(all(-50.0 < db <= -20.0 for db, _y, _lab in grid))
        # More lines arriving do not pull a manual scale back to auto.
        self.feed(v, noise_lines(v, 20, seed=2, t0=10.0))
        v.repaint()
        self.assertEqual((v.db_lo, v.db_hi), (-50.0, -20.0))

        pop.spec_auto.set_on(True, emit=True)
        v.repaint()
        self.assertEqual((v.db_hi, v.db_hi - v.db_lo), v.auto_scale())

    def test_scale_prefs_survive_a_restart(self):
        from ohscore.ui.prefs import Prefs
        v = self.scope("wide")
        self.prefs["specAuto"], self.prefs["specTop"], self.prefs["specRange"] = False, -30.0, 60.0
        self.prefs.save()
        v2 = self.scope("wide", prefs=Prefs(os.path.join(self.tmp, "ui.json")))
        self.feed(v2, noise_lines(v2, 10))
        v2.repaint()
        self.assertEqual((v2.db_lo, v2.db_hi), (-90.0, -30.0))
        self.assertIsNot(v, v2)

    def test_the_panel_fits_a_laptop_screen(self):
        v = self.scope("zoom")
        self.feed(v, noise_lines(v, 10))
        pop = self.adjust(v)
        for key, _label in pop.tabs.options:
            pop.tabs._choose([k for k, _ in pop.tabs.options].index(key))
            self.assertEqual(self.prefs["adjustTab"], key)
            pop.adjustSize()
            self.assertLess(pop.sizeHint().height(), 600, key)   # 1366x768, under the window's chrome


class PeakHold(ScopeCase):
    def setUp(self):
        super().setUp()
        self.v = self.scope("zoom")
        self.f = (self.v.fmap.lo + self.v.fmap.hi) / 2 + 1000.0
        self.col = int(self.v.fmap.x(self.f))
        self.t = 0.0

    def run_lines(self, seconds, carrier=None):
        n = int(round(seconds / 0.05))
        self.feed(self.v, carrier_lines(self.v, n, carrier, self.f, t0=self.t))
        self.t += n * 0.05

    def ghost(self):
        return float(self.v.peak[self.col - 2:self.col + 3].max())

    def test_default_holds_a_second_and_a_half_then_falls_ten_db_a_second(self):
        self.run_lines(1.0, carrier=-40.0)
        top = self.ghost()
        self.assertGreater(top, -45.0)
        self.run_lines(1.4)                        # the carrier is gone; the ghost holds
        self.assertAlmostEqual(self.ghost(), top, delta=0.01)
        self.run_lines(1.1)                        # ~1 s past the hold
        self.assertAlmostEqual(self.ghost(), top - 10.0, delta=1.5)

    def test_hold_and_fall_follow_the_panel(self):
        pop = self.adjust(self.v)
        pop.tabs._choose(1)                                   # Peaks
        pop.peak_hold._choose([k for k, _ in pop.peak_hold.options].index("3.0"))
        pop.peak_fall.set_value(40, emit=True)
        self.assertEqual((self.prefs["zoomSpecPeakHold"], self.prefs["zoomSpecPeakFall"]), (3.0, 40.0))
        self.assertEqual(self.prefs["specPeakHold"], 1.5)         # the wide scope keeps its own
        self.run_lines(1.0, carrier=-40.0)
        top = self.ghost()
        self.run_lines(2.9)
        self.assertAlmostEqual(self.ghost(), top, delta=0.01)
        self.run_lines(0.6)                        # ~0.5 s past the hold at 40 dB/s
        self.assertAlmostEqual(self.ghost(), top - 20.0, delta=3.0)

    def test_until_cleared_holds_until_clear(self):
        pop = self.adjust(self.v)
        pop.peak_hold._choose([k for k, _ in pop.peak_hold.options].index("-1.0"))
        self.assertEqual(self.prefs["zoomSpecPeakHold"], -1.0)
        self.run_lines(1.0, carrier=-40.0)
        top = self.ghost()
        self.run_lines(30.0)
        self.assertAlmostEqual(self.ghost(), top, delta=0.01)
        pop.peak_clear.clicked.emit()
        self.assertLess(self.ghost(), -90.0)                      # back on the floor with the trace
        np.testing.assert_array_equal(self.v.peak, self.v.avg)

    def test_off_hides_the_ghost_and_on_starts_it_afresh(self):
        pop = self.adjust(self.v)
        pop.peak_on.set_on(False, emit=True)
        self.assertFalse(self.prefs["zoomSpecPeak"])
        self.assertFalse(pop.peak_fall.isEnabled())
        self.run_lines(1.0, carrier=-40.0)
        self.assertFalse(self.v.peak_settings()[0])
        self.run_lines(0.5)
        pop.peak_on.set_on(True, emit=True)
        self.run_lines(0.1)
        self.assertLess(self.ghost(), -60.0)               # no stale ghost of the carrier
        self.v.repaint()                                   # and painting with it on or off is fine


class Smoothing(ScopeCase):
    def trace_after_step(self, smooth, seconds):
        """The trace and the ghost at a carrier `seconds` after it appears."""
        v = self.scope("zoom")
        if smooth is not None:
            pop = self.adjust(v)
            pop.smooth.set_value(smooth, emit=True)
            pop.close()
        f = (v.fmap.lo + v.fmap.hi) / 2 + 1000.0
        col = int(v.fmap.x(f))
        self.feed(v, carrier_lines(v, 20))
        self.feed(v, carrier_lines(v, int(round(seconds / 0.05)), -40.0, f, t0=1.0))
        sl = slice(col - 2, col + 3)
        return float(v.avg[sl].max()), float(v.peak[sl].max()), v

    def test_default_is_the_old_averaging(self):
        from ohscore.ui.prefs import DEFAULTS
        self.assertEqual(DEFAULTS["zoomSpecSmooth"], 0.13)
        trace, _ghost, _v = self.trace_after_step(None, 0.05)
        self.assertAlmostEqual(trace, -100.0 + 60.0 * 0.32, delta=0.3)   # 0.32 of the way, one line

    def test_raw_follows_each_line_and_heavy_lags(self):
        raw, ghost_raw, v = self.trace_after_step(0.0, 0.05)
        self.assertEqual(self.prefs["zoomSpecSmooth"], 0.0)
        self.assertEqual(self.prefs["specSmooth"], 0.13)            # the wide scope keeps its own
        self.assertAlmostEqual(raw, -40.0, delta=0.01)              # the line itself
        heavy, ghost_heavy, _v = self.trace_after_step(1.0, 0.5)
        self.assertAlmostEqual(heavy, -100.0 + 60.0 * (1 - np.exp(-0.5)), delta=0.6)
        # The ghost keeps the default averaging whatever the trace does.
        _d, ghost_default, _v = self.trace_after_step(None, 0.5)
        self.assertAlmostEqual(ghost_heavy, ghost_default, delta=0.01)
        _d, ghost_raw_later, _v = self.trace_after_step(0.0, 0.5)
        self.assertAlmostEqual(ghost_raw_later, ghost_default, delta=0.01)

    def test_the_waterfall_ignores_smoothing(self):
        rows = {}
        for smooth in (0.0, 1.0):
            _t, _g, v = self.trace_after_step(smooth, 1.0)
            rows[smooth] = v.wf.ordered()[:10].copy()
        np.testing.assert_array_equal(rows[0.0], rows[1.0])


class PeakMarkers(ScopeCase):
    def setUp(self):
        super().setUp()
        self.v = self.scope("zoom")
        self.mid = (self.v.fmap.lo + self.v.fmap.hi) / 2

    def marks_on(self, above=10, most=5, v=None):
        pop = self.adjust(v or self.v)
        pop.marks_on.set_on(True, emit=True)
        pop.mark_above.set_value(above, emit=True)
        pop.mark_max.set_value(most, emit=True)
        return pop

    def test_off_by_default(self):
        self.feed(self.v, carrier_lines(self.v, 40, -40.0, self.mid))
        self.assertFalse(self.prefs["zoomSpecMarks"])
        self.assertEqual(self.v.peak_marks.marks, [])

    def test_labels_the_strongest_with_frequency_and_level(self):
        pop = self.marks_on()
        self.assertTrue(self.prefs["zoomSpecMarks"])
        self.assertFalse(self.prefs["specMarks"])                     # the wide scope keeps its own
        f1, f2, f3 = self.mid - 3000, self.mid + 2000, self.mid + 4000
        self.feed(self.v, carrier_lines(self.v, 40, more=[(f1, -40.0), (f2, -70.0), (f3, -95.0)]))
        marks = self.v.peak_marks.marks
        self.assertEqual(len(marks), 2)                               # -95 is under floor + 10
        hzpp = self.v.fmap.hz_per_px
        self.assertAlmostEqual(marks[0][0], f1, delta=2 * hzpp)
        self.assertAlmostEqual(marks[0][1], -40.0, delta=1.0)
        self.assertAlmostEqual(marks[1][0], f2, delta=2 * hzpp)
        # The label says the frequency as the axis does, and the level.
        text = self.v.mark_label(*marks[0])
        self.assertTrue(text.startswith(self.v.face.axis_label(marks[0][0], 10)), text)
        self.assertTrue(text.endswith("-40"), text)
        self.v.repaint()
        self.assertEqual(len(self.v.mark_boxes()), 2)
        # Fewer allowed: the strongest stays.
        pop.mark_max.set_value(1, emit=True)
        self.assertEqual(self.prefs["zoomSpecMarkMax"], 1)
        self.assertEqual(len(self.v.peak_marks.marks), 1)
        self.assertAlmostEqual(self.v.peak_marks.marks[0][0], f1, delta=2 * hzpp)
        # A higher threshold drops the weaker; off clears them all.
        pop.mark_max.set_value(5, emit=True)
        pop.mark_above.set_value(35, emit=True)              # -70 is under -65 less the 3 dB grace
        self.assertEqual(len(self.v.peak_marks.marks), 1)
        pop.marks_on.set_on(False, emit=True)
        self.assertEqual(self.v.peak_marks.marks, [])

    def test_one_wide_signal_gets_one_label(self):
        self.marks_on()
        lo, hi = self.v.fmap.lo, self.v.fmap.hi
        nb = 1024
        bin_hz = (hi - lo) / nb
        rng = np.random.default_rng(7)
        lines = []
        for i in range(60):
            db = np.full(nb, -100.0, np.float32)
            a = int((self.mid - lo) / bin_hz)
            k = int(2400 / bin_hz)
            # An SSB voice: a 2.4 kHz hump, every bin of it a little
            # different every line - dozens of small maxima.
            db[a:a + k] = -55.0 + rng.uniform(-4, 4, k).astype(np.float32)
            lines.append(((i + 1) * 0.05, lo + bin_hz / 2, bin_hz, db))
        self.feed(self.v, lines)
        self.assertEqual(len(self.v.peak_marks.marks), 1)

    def test_markers_do_not_flicker(self):
        self.marks_on(above=10, most=1)
        # Two carriers within a fraction of a dB and noise on everything: a
        # fresh top-1 each time would swap between them.
        fa, fb = self.mid - 2000, self.mid + 2000
        # A third, sitting right on the threshold, with its own wobble.
        fc = self.mid + 4500
        seen, t = [], 0.0
        for k in range(40):
            self.feed(self.v, carrier_lines(self.v, 10, more=[(fa, -50.0), (fb, -50.3)], jitter=2.0, seed=k, t0=t))
            t += 0.5
            seen.append(tuple(round(f) for f, _ in self.v.peak_marks.marks))
        self.assertEqual(len(set(seen[2:])), 1, seen)
        self.v.prefs["zoomSpecMarkMax"] = 3
        self.v.refresh_marks()
        seen = []
        for k in range(40):
            self.feed(self.v, carrier_lines(self.v, 10, more=[(fa, -50.0), (fb, -50.3), (fc, -89.5)],
                                            jitter=2.0, seed=100 + k, t0=t))
            t += 0.5
            seen.append(len(self.v.peak_marks.marks))
        first = seen.index(3)
        self.assertTrue(all(n == 3 for n in seen[first:]), seen)     # once shown, it stays

    def test_labels_never_overlap(self):
        self.marks_on(above=10, most=10)
        hzpp = self.v.fmap.hz_per_px
        sigs = [(self.mid - 4000 + i * 40 * hzpp, -40.0 - i) for i in range(10)]
        self.feed(self.v, carrier_lines(self.v, 40, more=sigs))
        self.assertEqual(len(self.v.peak_marks.marks), 10)
        boxes = [b for _x, _y, b, _t in self.v.mark_boxes()]
        self.assertGreater(len(boxes), 3)
        for i, a in enumerate(boxes):
            self.assertTrue(self.v.r_spec.contains(a), a)
            for b in boxes[i + 1:]:
                self.assertFalse(a.intersects(b))

    def peak_under(self, v, cap, key):
        """Feed `v` one carrier placed so that its label's first place -
        centred just above the peak - lands square on the caption `cap`."""
        self.prefs[key + "Auto"] = False
        self.prefs[key + "Top"] = -20.0
        self.prefs[key + "Range"] = 100.0
        v._apply_scale()
        r = v.r_spec
        y = cap.center().y() + 16                       # the first try spans y - 24 .. y - 8
        level = v.db_lo + (r.bottom() - y) / (r.height() - 6) * (v.db_hi - v.db_lo)
        f = v.fmap.f(cap.center().x())
        self.feed(v, carrier_lines(v, 40, more=[(f, level)]))
        self.assertEqual(len(v.peak_marks.marks), 1)
        first = v.mark_boxes()
        self.assertEqual(len(first), 1, "there is room elsewhere: moved, not dropped")
        return first[0][2]

    def test_labels_keep_off_the_beacon_captions(self):
        # 0.1.3: "995.4  -49" drawn over the Multimedia beacon's caption.
        v = self.scope("wide", size=(1400, 420))
        self.marks_on(v=v)
        caps = v.caption_boxes()
        mm = v.beacon_layout()[2][2]                     # lower, middle, Multimedia, upper
        self.assertIsNotNone(mm)
        box = self.peak_under(v, mm, "spec")
        for c in caps:
            self.assertFalse(box.intersects(c), (box, c))
        # Placed again with nothing changed, it stays put.
        self.feed(v, carrier_lines(v, 10, more=[(m[0], m[1]) for m in v.peak_marks.marks], t0=10.0))
        self.assertEqual(v.mark_boxes()[0][2], box)

    def test_labels_keep_off_the_mode_flags(self):
        self.bridge.st["mode"] = "cw"
        self.bridge.st["cwPitch"] = 700.0
        self.v.update()
        self.marks_on()
        caps = self.v.caption_boxes()
        self.assertEqual(len(caps), 1)                   # PITCH 700
        box = self.peak_under(self.v, caps[0], "zoomSpec")
        self.assertFalse(box.intersects(caps[0]), (box, caps[0]))


class PeakArithmetic(unittest.TestCase):
    def test_running_max_is_the_window_maximum(self):
        from ohscore.ui.scopecore import running_max
        a = np.random.default_rng(0).standard_normal(300).astype(np.float32)
        for r in (0, 1, 2, 7, 8, 40):
            want = np.array([a[max(0, i - r):i + r + 1].max() for i in range(len(a))])
            np.testing.assert_array_equal(running_max(a, r), want)

    def test_find_peaks_spacing_threshold_and_position(self):
        from ohscore.ui.scopecore import find_peaks
        a = np.full(200, -100.0)
        a[50], a[49], a[51] = -40.0, -46.0, -52.0       # leans left: the true top is left of column 50
        a[55] = -45.0                                     # within the radius of the stronger: not counted
        a[120] = -80.0
        a[160] = -95.0                                    # under the threshold
        idx, off = find_peaks(a, -90.0, radius=8)
        self.assertEqual(sorted(idx.tolist()), [50, 120])
        self.assertLess(float(off[list(idx).index(50)]), 0.0)
        idx, _ = find_peaks(a, -90.0, radius=8, most=1)
        self.assertEqual(idx.tolist(), [50])


class ScopeColours(ScopeCase):
    def test_classic_is_exactly_the_original_look(self):
        from PyQt6.QtGui import QColor
        from ohscore.ui import scopelook, theme
        v = self.scope("wide")
        self.assertEqual(self.prefs["scopeLook"], {})
        self.feed(v, noise_lines(v, 20))
        v.repaint()
        lk = v.look
        # The literals the scope painted with before the look was adjustable.
        self.assertEqual(lk.trace_pen.color(), QColor(214, 238, 255, 235))
        self.assertEqual(lk.trace_pen.widthF(), 1.0)
        self.assertEqual(lk.width, 1)
        self.assertEqual(lk.peak_pen.color(), QColor(150, 170, 200, 70))
        self.assertEqual(lk.marker, QColor(255, 214, 102))
        self.assertEqual(lk.marker_edge.color(), QColor(255, 214, 102, 120))
        self.assertEqual(lk.grid_pen.color(), QColor("#141a23"))
        self.assertEqual(lk.background, theme.c("scope"))
        self.assertTrue(lk.fill)
        # The fill gradient, pixel for pixel, against the original formula.
        h = v._fill_buf.shape[0]
        k = np.linspace(0.0, 1.0, h)
        a = 0.50 * (1 - k) ** 1.4 + 0.04
        old = ((np.round(a * 255).astype(np.uint32) << 24) | (np.round((79 * (1 - k) + 20 * k) * a).astype(np.uint32)
                                                              << 16) |
               (np.round((209 * (1 - k) + 50 * k) * a).astype(np.uint32) << 8) |
               np.round((232 * (1 - k) + 110 * k) * a).astype(np.uint32))
        np.testing.assert_array_equal(v._grad, old)
        self.assertIs(scopelook.look(self.prefs), lk)                  # cached, not rebuilt per paint

    def test_a_preset_reaches_the_painted_scope(self):
        v = self.scope("zoom")
        self.feed(v, noise_lines(v, 200))
        img = v.grab().toImage()
        corner = img.pixelColor(int(v.width() * 0.37), int(v.r_spec.y() + 3))    # above the trace, off the grid
        self.prefs["scopeLook"] = {"preset": "green"}
        v.repaint()
        img = v.grab().toImage()
        self.assertEqual(img.pixelColor(int(v.width() * 0.37), int(v.r_spec.y() + 3)).name(), "#020804")
        self.assertNotEqual(corner.name(), "#020804")
        self.assertEqual(v.look.trace_pen.color().green(), 255)
        # Fill off: nothing painted under the trace any more.
        self.prefs["scopeLook"] = {"preset": "custom", "fill": False, "background": "#000000"}
        v.repaint()
        img = v.grab().toImage()
        foot = img.pixelColor(int(v.width() * 0.37), int(v.r_spec.bottom() - 2))
        self.assertEqual((foot.red(), foot.green(), foot.blue()), (0, 0, 0))

    def test_a_bad_stored_value_falls_back_to_the_preset(self):
        from ohscore.ui import scopelook
        vals = scopelook.values({"preset": "nonsense", "trace": "not a colour", "traceWidth": "2", "fill": 1})
        self.assertEqual({k: vals[k] for k in ("preset", "trace", "traceWidth", "fill")},
                         {"preset": "classic", "trace": scopelook.PRESETS["classic"]["trace"], "traceWidth": 1,
                          "fill": True})

    def test_the_editor_stores_presets_by_name_and_custom_whole(self):
        from ohscore.ui.lookedit import LookEditor
        ed = LookEditor({})
        self.assertEqual(ed.preset.value, "classic")
        self.assertEqual(ed.stored(), {})
        ed.preset._choose(1)                                           # Amber
        self.assertEqual(ed.stored(), {"preset": "amber"})
        ed.set_item("marker", "#ff00ff")                               # any change makes it Custom
        self.assertEqual(ed.preset.value, "custom")
        st = ed.stored()
        self.assertEqual((st["preset"], st["marker"], st["background"]), ("custom", "#ff00ff", "#0a0703"))
        self.assertEqual(ed.preview.look.marker.name(), "#ff00ff")
        ed.fill.set_on(False, emit=True)
        self.assertFalse(ed.stored()["fill"])
        self.assertFalse(ed.fill_opacity.isEnabled())
        ed.width_seg._choose(2)
        self.assertEqual(ed.stored()["traceWidth"], 3)
        ed.deleteLater()
        ed2 = LookEditor(st)                                           # opens on what was saved
        self.assertEqual(ed2.buttons["marker"].value, "#ff00ff")
        reset = next(b for b in ed2.findChildren(__import__("ohscore.ui.controls", fromlist=["Button"]).Button)
                     if b.text == "Reset to default")
        reset.clicked.emit()
        self.assertEqual(ed2.stored(), {})
        ed2.deleteLater()

    def test_colours_button_asks_for_settings(self):
        v = self.scope("zoom")
        asked = []
        v.colours_requested.connect(lambda: asked.append(True))
        pop = self.adjust(v)
        btn = next(b for b in pop.findChildren(__import__("ohscore.ui.controls", fromlist=["Button"]).Button)
                   if b.text.startswith("Colours"))
        btn.clicked.emit()
        self.assertEqual(asked, [True])
        self.assertFalse(pop.isVisible())


class StartUp(ScopeCase):
    def test_the_engine_publishes_no_line_of_zeros(self):
        from ohscore.dsp.spectrum import Scope
        sc = Scope(48_000.0, 1024, 20, 2)
        rng = np.random.default_rng(0)
        x = ((rng.standard_normal(48_000) + 1j * rng.standard_normal(48_000)) * 1e-3).astype(np.complex64)
        lines = sc.process(x[:5000]) + sc.process(x[5000:])
        self.assertTrue(lines)
        self.assertGreater(min(float(db.min()) for _e, db in lines), -150.0)

    def test_the_scale_settles_in_a_second_even_after_an_odd_first_line(self):
        v = self.scope("zoom")
        lo, hi = v.fmap.lo, v.fmap.hi
        odd = (0.0, lo, (hi - lo) / 1024, np.full(1024, -200.0, np.float32))
        self.feed(v, [odd] + noise_lines(v, 20, t0=0.0))
        v.repaint()
        self.assertLess(v.db_lo, v.floor - 6)
        self.assertGreater(v.db_hi, v.floor + 30)


class ScaledScreen(ScopeCase):
    """A screen scaled by other than 100 % (KDE's 105 % on the test laptop,
    125 % on many Windows laptops). The trace there was drawn with a pen
    wider than one device pixel, which Qt strokes the slow way - ~50x the
    time, with the GIL held, so receive overran (07/10)."""

    def render_ms(self, v, dpr: float) -> float:
        """The scope painted into an image of device-pixel ratio `dpr`, as
        the window system would on a screen scaled that much: best of 3."""
        import time

        from PyQt6.QtGui import QImage
        img = QImage(int(v.width() * dpr), int(v.height() * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        best = float("inf")
        for _ in range(3):
            img.fill(0)
            t0 = time.perf_counter()
            v.render(img)
            best = min(best, time.perf_counter() - t0)
        return best * 1000.0

    def test_a_scaled_screen_paints_about_as_fast_as_an_unscaled_one(self):
        v = self.scope("zoom", size=(1800, 420))
        self.feed(v, noise_lines(v, 40))
        plain = self.render_ms(v, 1.0)
        scaled = self.render_ms(v, 1.05)
        # More pixels cost a little more (1.05 squared: 1.5 -> 1.9 ms on a
        # desktop); the slow stroker cost 12x here (18 ms) and ~50x on the
        # laptop. The 3 ms is for a busy machine's noise on a fast paint.
        self.assertLess(scaled, 2 * plain + 3.0, f"{scaled:.1f} ms at 105 % against {plain:.1f} ms at 100 %")

    def test_the_trace_is_as_wide_as_chosen_at_any_scale(self):
        """Drawn as the scope draws it - the look's pen, at trace_passes'
        offsets - a level trace covers about `width` logical pixels: the
        same device pixels as before at 100 %, and not a hairline at 200 %."""
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QImage, QPainter

        from ohscore.ui import scopelook
        look = scopelook.Look({})

        def rows(width, dpr):
            img = QImage(int(100 * dpr), int(40 * dpr), QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            img.fill(0)
            p = QPainter(img)
            p.setPen(look.trace_pen)
            for dx, dy in scopelook.trace_passes(width, dpr):
                p.translate(dx, dy)
                p.drawLine(QPointF(0, 20), QPointF(100, 20))
                p.translate(-dx, -dy)
            p.end()
            x = img.width() // 2
            return sum(1 for y in range(img.height()) if img.pixelColor(x, y).alpha() > 0)

        for width, dpr, device_rows in ((1, 1.0, 1), (2, 1.0, 2), (3, 1.0, 3), (1, 1.05, 1),
                                        (1, 2.0, 2), (2, 2.0, 4), (3, 2.0, 4)):
            with self.subTest(width=width, dpr=dpr):
                self.assertEqual(rows(width, dpr), device_rows)


class RbwArithmetic(unittest.TestCase):
    """scopecore.rbw_line on lines from the engine's own Scope: what a wider
    resolution bandwidth does to a carrier and to noise."""

    def line(self, x, rate=12_000.0, nfft=1024, avg=64):
        from ohscore.dsp.spectrum import Scope
        sc = Scope(rate, nfft, 1.0, avg)
        return sc.process(x.astype(np.complex64))[-1][1], rate / nfft

    def test_a_carrier_keeps_its_level_and_noise_rises_by_the_bandwidth(self):
        from ohscore.ui.scopecore import rbw_line
        rng = np.random.default_rng(4)
        n = 12_000 * 4
        tone = 0.01 * np.exp(2j * np.pi * 1234.5 * np.arange(n) / 12_000.0)   # between two bins
        noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 1e-3
        db, bin_hz = self.line(tone + noise)
        wide, rbw = rbw_line(db, bin_hz, 100.0)
        k = round(100.0 / bin_hz)
        self.assertAlmostEqual(rbw, k * bin_hz)
        # The carrier: -40 dBFS. The fine line loses up to 1.4 dB to
        # scalloping between bins; the wide one keeps it all.
        self.assertAlmostEqual(float(wide.max()), -40.0, delta=0.3)
        self.assertGreater(float(wide.max()), float(db.max()) - 0.05)
        # Noise, away from the carrier: up by 10 log10(k / 1.5).
        quiet = slice(100, 300)
        rise = float(np.median(wide[quiet]) - np.median(db[quiet]))
        self.assertAlmostEqual(rise, 10 * np.log10(k / 1.5), delta=0.6)
        # The ends of the line do not droop (partial windows are scaled up).
        self.assertAlmostEqual(float(np.median(wide[:k])), float(np.median(wide[quiet])), delta=1.0)

    def test_a_fine_rbw_returns_the_line_untouched_and_never_writes_to_it(self):
        from ohscore.ui.scopecore import rbw_line
        db = np.random.default_rng(1).uniform(-110, -60, 512).astype(np.float32)
        before = db.copy()
        out, rbw = rbw_line(db, 10.0, 20.0)                 # two bins: under the three a carrier needs
        self.assertIs(out, db)
        self.assertAlmostEqual(rbw, 15.0)                   # the Hann window's 1.5 bins
        rbw_line(db, 10.0, 200.0)
        np.testing.assert_array_equal(db, before)


def qo100_signals(seconds=4.0, seed=7):
    """12 kHz complex baseband around the zoom's centre, as the zoom scope
    sees the downlink: a CW carrier at -3 kHz, the middle beacon's 400-baud
    Manchester BPSK at 0 Hz and an FT8 transmission at +3 kHz, all at the
    same power (-40 dBFS), over a weak noise floor."""
    from ohscore.devices.simsignals import bpsk_beacon, ft8_like
    rng = np.random.default_rng(seed)
    rate = 12_000.0
    n = int(seconds * rate)
    t = np.arange(n) / rate
    a = 0.01
    cw = a * np.exp(2j * np.pi * -3000.0 * t)
    psk = a * bpsk_beacon(rng, seconds + 1)[:n]
    ft8 = a * ft8_like(rng, 3000.0)[:n]
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 3e-5
    return (cw + psk + ft8 + noise).astype(np.complex64), rate


class DisplayStyle(ScopeCase):
    """The zoom scope's two display styles on the same engine lines: what
    each makes of a carrier, the PSK beacon and FT8 beside each other, and
    that neither changes the lines everything else measures from."""

    def lines(self, v):
        from ohscore.dsp.spectrum import Scope, wide_nfft
        x, rate = qo100_signals()
        sc = Scope(rate, wide_nfft(1024, rate, 12_000.0), 20.0, 2)
        start = (v.fmap.lo + v.fmap.hi) / 2 - sc.nfft // 2 * sc.bin_hz
        out = []
        for i in range(0, len(x), 600):                     # 50 ms blocks, as the engine hands them on
            for end, db in sc.process(x[i:i + 600]):
                out.append((end / rate, start, sc.bin_hz, db))
        return out

    def heights(self, style):
        """({signal: the trace's top over it} after 4 s, the RBW caption, the scope)."""
        v = self.scope("zoom")
        if style is not None:
            pop = self.adjust(v)
            pop.style._choose([k for k, _ in pop.style.options].index(style))
            pop.close()
        lines = self.lines(v)
        before = [db.copy() for _t, _s, _b, db in lines]
        self.feed(v, lines)
        for (_t, _s, _b, db), was in zip(lines, before):
            np.testing.assert_array_equal(db, was)          # the engine's lines are never written to
        centre = (v.fmap.lo + v.fmap.hi) / 2
        top = {}
        for name, lo, hi in (("cw", -3050, -2950), ("psk", -700, 700), ("ft8", 2990, 3060)):
            c0, c1 = int(v.fmap.x(centre + lo)), int(v.fmap.x(centre + hi)) + 1
            top[name] = float(v.avg[c0:c1].max())
        return top, v.rbw_text(), v

    def test_standard_is_the_default_and_draws_the_fine_bins(self):
        from ohscore.ui.prefs import DEFAULTS
        self.assertEqual((DEFAULTS["specStyle"], DEFAULTS["zoomSpecStyle"]), ("nb", "nb"))
        top, rbw, v = self.heights(None)
        self.assertEqual(v.display_style(), "nb")
        self.assertEqual(rbw, "RBW 18 Hz")               # 12 kHz over 1024 bins, Hann
        self.assertAlmostEqual(top["cw"], -40.0, delta=1.5)
        # Spread over ~1 kHz, the beacon reads its power per 12 Hz bin: far
        # under a carrier of the same power. Ray's "the beacon looks low".
        self.assertGreater(top["cw"] - top["psk"], 12.0)

    def test_sdr_console_like_brings_the_wide_beacon_up_to_the_narrow_signals(self):
        std, _rbw, _v = self.heights("nb")
        sdrc, rbw, v = self.heights("sdrconsole")
        self.assertEqual(self.prefs["zoomSpecStyle"], "sdrconsole")
        self.assertEqual(self.prefs["specStyle"], "nb")      # the wide scope keeps its own
        self.assertEqual(rbw, "RBW 105 Hz")              # ~100 Hz: nine 11.7 Hz bins
        # A carrier keeps its level in either style...
        self.assertAlmostEqual(sdrc["cw"], std["cw"], delta=1.5)
        # ...the beacon gains what a 100 Hz filter collects of it...
        self.assertGreater((std["cw"] - std["psk"]) - (sdrc["cw"] - sdrc["psk"]), 6.0)
        self.assertLess(sdrc["cw"] - sdrc["psk"], 9.0)
        # ...and FT8, one 6.25 Hz tone at a time inside the 100 Hz, reads
        # its whole power as one block, as high as the carrier.
        self.assertLess(abs(sdrc["cw"] - sdrc["ft8"]), 2.0)

    def test_the_waterfall_follows_the_style(self):
        """The rows the waterfall is given, in dB (its colours clip a strong
        carrier, which would hide the difference): the beacon stands as
        close to the carrier there as on the trace."""
        from ohscore.ui.scopecore import Waterfall
        gap = {}
        for style in ("nb", "sdrconsole"):
            rows = []
            real = Waterfall.push_db

            def push(wf, cols, fl, rg, rows=rows, real=real):
                rows.append(cols.copy())
                real(wf, cols, fl, rg)
            with mock.patch.object(Waterfall, "push_db", push):
                top, _rbw, v = self.heights(style)
            row = np.mean(rows[-10:], axis=0)
            centre = (v.fmap.lo + v.fmap.hi) / 2

            def col(f):
                return int(v.fmap.x(centre + f) * v.wf.w / v.width())
            gap[style] = float(row[col(-3050):col(-2950) + 1].max() - row[col(-700):col(700) + 1].max())
            trace_gap = top["cw"] - top["psk"]
            self.assertAlmostEqual(gap[style], trace_gap, delta=3.0, msg=style)
        self.assertGreater(gap["nb"] - gap["sdrconsole"], 6.0)

    def test_an_unknown_stored_style_is_standard(self):
        from ohscore.ui.prefs import Prefs
        path = os.path.join(self.tmp, "ui.json")
        with open(path, "w") as f:
            f.write('{"zoomSpecStyle": "spectran"}')
        v = self.scope("zoom", prefs=Prefs(path))
        self.assertEqual(v.display_style(), "nb")

    def test_the_rbw_caption_sits_in_the_axis_clear_of_its_labels(self):
        for style in ("nb", "sdrconsole"):
            _top, _rbw, v = self.heights(style)
            box = v.rbw_box()
            self.assertIsNotNone(box)
            self.assertTrue(v.r_axis.contains(box), style)
            self.assertGreaterEqual(v._axis_caption_rect().right(), box.right())
            labels = v._axis_labels()
            self.assertTrue(labels, style)
            for _x, lab_box, lab in labels:
                self.assertFalse(lab_box.intersects(box), (style, lab))


if __name__ == "__main__":
    unittest.main()
