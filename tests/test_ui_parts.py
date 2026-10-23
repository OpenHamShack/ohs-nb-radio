"""The UI's arithmetic, tested without a window: frequency parsing, the
pixel map, spectrum resampling, the waterfall ring, palettes, the FT8
sequencer, click-to-tune and the preferences file."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Parts(unittest.TestCase):
    def test_parse_freq_accepts_what_operators_type(self):
        from ohsnb.ui.face import parse_freq
        self.assertEqual(parse_freq("10489.540"), 10_489_540_000)
        self.assertEqual(parse_freq("10489.540.250"), 10_489_540_250)
        self.assertEqual(parse_freq("10489540000"), 10_489_540_000)
        self.assertEqual(parse_freq("489.75"), 10_489_750_000)
        self.assertEqual(parse_freq("540"), 10_489_540_000)
        self.assertEqual(parse_freq("540.25 kHz"), 10_489_540_250)
        self.assertEqual(parse_freq("2400.040"), 10_489_540_000)      # uplink, converted
        for bad in ("hello", "10491.000", "200", "2400.6"):
            with self.assertRaises(ValueError):
                parse_freq(bad)

    def test_qrz_link_uses_the_home_call(self):
        from ohscore.ui.logbook import qrz_call, qrz_url
        self.assertEqual(qrz_call("g4abc"), "G4ABC")
        self.assertEqual(qrz_call("G4ABC/P"), "G4ABC")
        self.assertEqual(qrz_call("EA8/G4ABC"), "G4ABC")
        self.assertEqual(qrz_call("F/M0XYZ/MM"), "M0XYZ")
        self.assertEqual(qrz_call(" 2E0AAA "), "2E0AAA")
        self.assertEqual(qrz_url("G4ABC/P"), "https://www.qrz.com/db/G4ABC")

    def test_freqmap_round_trip(self):
        from ohscore.ui.scopecore import FreqMap
        fm = FreqMap(10_489_475_000.0, 10_490_025_000.0, 1873, x0=12.0)
        for f in (10_489_475_000.0, 10_489_612_345.6, 10_490_025_000.0):
            self.assertAlmostEqual(fm.f(fm.x(f)), f, places=3)
        self.assertAlmostEqual(fm.x(fm.lo), 12.0)
        self.assertAlmostEqual(fm.x(fm.hi), 12.0 + 1873)

    def test_resample_keeps_a_one_bin_signal(self):
        from ohscore.ui.scopecore import resample
        db = np.full(2064, -100.0, np.float32)
        db[1000] = -40.0                              # one narrow carrier
        start, bw = 10_489_475_000.0, 266.7
        f_sig = start + 1000 * bw
        for n in (400, 1000, 1920):
            cols = resample(start, bw, db, start - bw / 2, start + 2064 * bw - bw / 2, n, -150.0)
            self.assertEqual(cols.max(), -40.0)       # never averaged away, whatever the width
            col = int((f_sig - (start - bw / 2)) / ((2064 * bw) / n))
            self.assertIn(int(np.argmax(cols)), (col - 1, col, col + 1))
        # Zoomed in past the bin width it interpolates, and outside the line it fills.
        cols = resample(start, bw, db, f_sig - 2000, f_sig + 2000, 400, -150.0)
        self.assertAlmostEqual(float(cols.max()), -40.0, delta=3.0)
        cols = resample(start, bw, db, start - 50_000, start - 10_000, 100, -150.0)
        self.assertTrue(np.all(cols == -150.0))

    def test_waterfall_ring_newest_first(self):
        from ohscore.ui.scopecore import Waterfall
        wf = Waterfall(16, 8)
        for k in range(20):
            wf.push_row(np.full(16, k, np.uint32))
        rows = wf.ordered()
        self.assertEqual([int(r[0]) for r in rows], list(range(19, 11, -1)))
        self.assertEqual(wf.rows_total, 20)
        wf.resize(32, 8)                               # history survives a resize
        self.assertEqual(int(wf.ordered()[0][0]), 19)

    def test_waterfall_remap_follows_frequency(self):
        from ohscore.ui.scopecore import Waterfall
        wf = Waterfall(100, 4)
        row = np.zeros(100, np.uint32)
        row[50] = 7                                    # something at 1050 Hz on a 1000-1100 Hz view
        wf.push_row(row)
        wf.remap(1000.0, 1100.0, 1020.0, 1120.0)       # pan up by 20 Hz: it moves 20 columns left
        self.assertEqual(int(np.argmax(wf.ordered()[0])), 30)

    def test_palettes(self):
        from ohscore.ui import palettes
        for name in palettes.NAMES:
            lut = palettes.lut(name)
            self.assertEqual(lut.shape, (256,))
            self.assertTrue(np.all(lut >> 24 == 0xFF))
            lum = [((int(v) >> 16 & 255) + (int(v) >> 8 & 255) + (int(v) & 255)) for v in lut]
            self.assertLess(lum[0], 60)                # the floor is dark
            self.assertGreater(lum[-1], lum[0] + 300)  # strong signals are bright

    def test_click_to_dial(self):
        from ohscore.ui.tuning import click_to_dial
        st = {"cwPitch": 700.0}
        self.assertEqual(click_to_dial("usb", 10_489_701_234.0, st), 10_489_701_200.0)
        self.assertEqual(click_to_dial("cw", 10_489_520_712.0, st), 10_489_520_010.0)
        self.assertEqual(click_to_dial("ft8", 10_489_541_700.0, st), 10_489_540_000.0)
        self.assertEqual(click_to_dial("psk31", 10_489_568_500.0, st, 1000.0), 10_489_567_500.0)

    def test_prefs_survive_garbage(self):
        from ohscore.ui.prefs import Prefs
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "ui.json")
            with open(p, "w") as f:
                json.dump({"licenceAck": "yes", "theme": "light", "wfFloor": -100, "nonsense": 1}, f)
            pr = Prefs(p)
            self.assertFalse(pr["licenceAck"])         # a wrong type never acknowledges the licence
            self.assertEqual(pr["theme"], "light")
            self.assertEqual(pr["wfFloor"], -100.0)
            pr["palette"] = "Glacier"
            pr.save()
            self.assertEqual(Prefs(p)["palette"], "Glacier")
            with open(p, "w") as f:
                f.write("{not json")
            self.assertFalse(Prefs(p)["licenceAck"])
        finally:
            shutil.rmtree(d)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class LockBadgeLayout(unittest.TestCase):
    """The TX/RX lock badges must never draw the error value over the title
    or the state word, however long the value or however narrow the badge.
    A real bug shipped because the old layout, when the value didn't fit
    beside the word, moved it up onto the title's row with no check against
    what was already drawn there - "-2.900 kHz" landed on top of "OWN
    SIGNAL". These drive the same geometry the paint code uses."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def test_detail_stays_clear_of_the_word_or_is_omitted(self):
        from ohscore.ui import theme
        from ohsnb.ui.status import LockBadge
        from PyQt6.QtGui import QFontMetricsF

        word_fm = QFontMetricsF(theme.font(13.5, theme.QFont.Weight.Bold))
        detail_fm = QFontMetricsF(theme.font(12, theme.QFont.Weight.Medium, mono=True))
        # Narrow badge and a long value both stress the "no room" path; a
        # wide badge and a short value exercise the normal fit.
        for row_right, word, detail in (
            (152.0, "SEARCHING", "-2.900 kHz"),
            (152.0, "LOCKED", "+0.0 Hz"),
            (60.0, "SEARCHING", "-123456.789 kHz"),
            (300.0, "LOST", "—"),
        ):
            word_right = 40 + word_fm.horizontalAdvance(word)
            text, x, w = LockBadge._place_detail(word_right, row_right, detail, detail_fm)
            if text:
                # The value's slot starts after the word (plus its gap) and
                # ends at or before the row's edge: it cannot reach back
                # over the word, and the row never includes the title's row.
                self.assertGreaterEqual(x, word_right)
                self.assertLessEqual(x + w, row_right + 0.01)
                self.assertLessEqual(detail_fm.horizontalAdvance(text), w + 0.01)
            else:
                # No usable room: the value is omitted rather than drawn
                # somewhere it would collide (it's still in the tooltip).
                self.assertLess(row_right - word_right, detail_fm.horizontalAdvance("…") + 8)

    def test_title_is_elided_not_overflowed(self):
        from ohsnb.ui.status import LockBadge
        b = LockBadge("TX · own signal, with a great many extra words")
        b.resize(150, 48)
        b.set_state("searching", "-2.900 kHz", [])
        pix = b.grab()
        self.assertEqual(pix.width(), 150)   # paints without raising on a tight, long title


class AudioTestRidesTheEngine(unittest.TestCase):
    """Settings' audio check opened its own PortAudio stream even for the
    device the running engine already had open, which a bare ALSA device
    refuses as "busy" - a real failure, but not the one it was reported as.
    It should ride the engine's stream only for that one matching device,
    and still probe independently for any other candidate (so an operator
    can audition a device before switching to it). PortAudio opens are
    mocked out: this is about the routing decision, not real hardware."""

    @staticmethod
    def _fake_engine(in_name="USB Headset", out_name="USB Headset", level=-18.0):
        fake = mock.MagicMock()
        fake.name = "portaudio"
        fake.in_name, fake.out_name = in_name, out_name
        fake.mic_level.return_value = level
        fake.open_mic.return_value = ""
        return fake

    def test_matching_input_reads_the_engines_level_not_its_own(self):
        from ohscore.ui.audiotest import AudioTester
        tester = AudioTester()
        fake = self._fake_engine()
        self.assertEqual(tester.start_input("USB Headset", engine_audio=fake), "")
        self.assertEqual(tester.level(), -18.0)
        fake.mic_level.assert_called()
        self.assertIsNone(tester.stream)        # no PortAudio stream of its own was opened
        tester.stop_input()
        self.assertEqual(tester.level(), -120.0)

    def test_riding_the_engine_opens_its_microphone_for_the_check_only(self):
        # The engine keeps no microphone open (ohscore/audio.py): the check
        # opens it for as long as it runs and lets go when it stops.
        from ohscore.ui.audiotest import AudioTester
        tester = AudioTester()
        fake = self._fake_engine()
        tester.start_input("USB Headset", engine_audio=fake)
        fake.open_mic.assert_called_once()
        fake.close_mic.assert_not_called()
        tester.stop_input()
        fake.close_mic.assert_called_once()
        tester.stop_input()                     # a second stop lets go of nothing more
        fake.close_mic.assert_called_once()

    def test_an_engine_microphone_that_will_not_open_is_the_checks_error(self):
        from ohscore.ui.audiotest import AudioTester
        tester = AudioTester()
        fake = self._fake_engine()
        fake.open_mic.return_value = "No microphone (denied)"
        self.assertEqual(tester.start_input("USB Headset", engine_audio=fake), "No microphone (denied)")
        fake.close_mic.assert_called_once()     # its claim given back at once
        self.assertEqual(tester.level(), -120.0)

    def test_system_default_on_both_sides_counts_as_matching(self):
        from ohscore.ui.audiotest import AudioTester
        tester = AudioTester()
        fake = self._fake_engine(in_name="", out_name="")
        self.assertEqual(tester.start_input("", engine_audio=fake), "")
        self.assertEqual(tester.level(), -18.0)

    def test_a_different_candidate_does_not_touch_the_engine(self):
        from ohscore.ui.audiotest import AudioTester
        tester = AudioTester()
        fake = self._fake_engine(in_name="Built-in Mic")
        with mock.patch.object(AudioTester, "_pa", side_effect=RuntimeError("no hardware here")):
            err = tester.start_input("USB Headset", engine_audio=fake)
        self.assertNotEqual(err, "")
        fake.mic_level.assert_not_called()

    def test_no_running_engine_falls_back_to_its_own_probe(self):
        from ohscore.ui.audiotest import AudioTester
        tester = AudioTester()
        with mock.patch.object(AudioTester, "_pa", side_effect=RuntimeError("no hardware here")):
            err = tester.start_input("USB Headset", engine_audio=None)
        self.assertNotEqual(err, "")

    def test_matching_output_plays_the_tone_through_the_engine(self):
        from ohscore.ui.audiotest import AudioTester
        tester = AudioTester()
        fake = self._fake_engine()
        self.assertEqual(tester.tone("USB Headset", engine_audio=fake), "")
        fake.play.assert_called_once()
        played = fake.play.call_args[0][0]
        self.assertGreater(len(played), 0)
        self.assertLessEqual(float(np.max(np.abs(played))), 0.31)   # peak-limited test tone, never clips


class Ft8Sequence(unittest.TestCase):
    def test_answering_a_cq_through_to_the_log(self):
        from ohscore.ft8seq import Sequencer
        s = Sequencer("GM4BRI", "IO86ha")
        s.answer("DL1ABC", "JO31", snr=-7)
        self.assertEqual(s.message(), "DL1ABC GM4BRI IO86")
        self.assertEqual(s.heard("GM4BRI DL1ABC -12", snr=-8)["next"], 3)
        self.assertEqual(s.message(), "DL1ABC GM4BRI R-08")
        self.assertEqual(s.heard("GM4BRI DL1ABC RR73")["next"], 5)
        self.assertEqual(s.message(), "DL1ABC GM4BRI 73")
        self.assertTrue(s.sent_now(5))                 # 73 sent with reports exchanged: log it
        self.assertFalse(s.sent_now(5))                # once

    def test_someone_answers_our_cq(self):
        from ohscore.ft8seq import Sequencer
        s = Sequencer("GM4BRI", "IO86")
        self.assertEqual(s.message(), "CQ GM4BRI IO86")
        r = s.heard("GM4BRI EA4QRP IN80", snr=-15)
        self.assertEqual((r["next"], r["new_dx"]), (2, "EA4QRP"))
        self.assertEqual(s.message(), "EA4QRP GM4BRI -15")
        self.assertEqual(s.heard("GM4BRI EA4QRP R-09")["next"], 4)
        s.sent_now(4)
        r = s.heard("GM4BRI EA4QRP 73")
        self.assertTrue(r["log"])
        self.assertEqual(s.rcvd, "-09")

    def test_ignores_other_stations(self):
        from ohscore.ft8seq import Sequencer
        s = Sequencer("GM4BRI", "IO86")
        s.answer("DL1ABC", "JO31")
        self.assertIsNone(s.heard("GM4BRI F5KLM -10")["next"])
        self.assertIsNone(s.heard("G4XYZ DL1ABC -10")["next"])
        self.assertEqual(s.next, 1)


if __name__ == "__main__":
    unittest.main()
