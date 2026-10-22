"""Engine.set_mode_tuned (Brian, 07/10/2026): picking a mode with a usual
operating frequency tunes there, unless the dial already counts as being
in it, Settings' modeAutoTune is off, or the radio is keyed. The rule
itself is shared (ohscore/engine.py); this exercises each app's own table
of usual places - ohsnb/bandplan.py MODE_SPOTS, ohsradio/radio.py's per-band
lookup - end to end through Radio.set_mode_tuned, never by reading either
table's source."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import tempfile
import unittest

from helpers import make_radio, noise_audio, run_sim
from ohsradio import bands


class Nb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def radio(self, start=False, audio=None, **over):
        r = make_radio(self.tmp, audio_source=audio, **over)
        self.radios.append(r)
        if start:
            r.start()
        return r

    def test_from_ssb_picking_ft8_lands_on_the_narrow_digi_mark(self):
        r = self.radio(mode="usb", vfo=10_489_700_000.0)
        r.set_mode_tuned("ft8")
        s = r.state()
        self.assertEqual(s["mode"], "ft8")
        self.assertEqual(s["vfo"], 10_489_540_000.0)

    def test_already_within_3khz_of_the_ft8_mark_stays_put(self):
        r = self.radio(mode="usb", vfo=10_489_541_000.0)
        r.set_mode_tuned("ft8")
        self.assertEqual(r.state()["vfo"], 10_489_541_000.0)

    def test_the_setting_off_leaves_the_dial_alone(self):
        r = self.radio(mode="usb", vfo=10_489_700_000.0, modeAutoTune=False)
        r.set_mode_tuned("ft8")
        s = r.state()
        self.assertEqual(s["mode"], "ft8")
        self.assertEqual(s["vfo"], 10_489_700_000.0)

    def test_the_contest_mark_wins_when_it_is_nearer(self):
        r = self.radio(mode="usb", vfo=10_489_860_000.0)
        r.set_mode_tuned("ft8")
        self.assertEqual(r.state()["vfo"], 10_489_870_000.0)

    def test_ft8_q65_and_js8_each_go_to_their_own_mark_in_the_narrow_segment(self):
        # Mac test 17/10/2026 (findings 17, 22): from FT8's .540, Q65 and JS8
        # left the dial on the FT8 signals, the whole segment counting as
        # "there" for each.
        r = self.radio(mode="ft8", vfo=10_489_540_000.0)
        for mode, mark in (("q65", 10_489_545_000.0), ("js8", 10_489_548_000.0), ("q65", 10_489_545_000.0),
                           ("ft8", 10_489_540_000.0), ("js8", 10_489_548_000.0), ("ft4", 10_489_540_000.0)):
            r.set_mode_tuned(mode)
            s = r.state()
            self.assertEqual((s["mode"], s["vfo"]), (mode, mark))
        # A dial a little above a mark is still on that mode's signals.
        r.set(vfo=10_489_546_500.0)
        r.set_mode_tuned("q65")
        self.assertEqual(r.state()["vfo"], 10_489_546_500.0)
        r.set(vfo=10_489_560_000.0)
        r.set_mode_tuned("js8")
        self.assertEqual(r.state()["vfo"], 10_489_560_000.0)

    def test_modes_with_no_usual_place_leave_the_dial(self):
        r = self.radio(mode="ft8", vfo=10_489_540_000.0)
        for mode in ("psk31", "psk63", "psk125", "rtty", "sstv", "hsmodem", "usb"):
            r.set_mode_tuned(mode)
            self.assertEqual(r.state()["vfo"], 10_489_540_000.0, mode)

    def test_a_mode_pick_while_keyed_does_not_retune(self):
        r = self.radio(start=True, mode="usb", vfo=10_489_700_000.0, audio=noise_audio())
        r.ptt(True)
        run_sim(r, 0.3)
        self.assertTrue(r.state()["keyed"])
        r.set_mode_tuned("ft8")      # would otherwise land on 10489.540
        self.assertEqual(r.state()["vfo"], 10_489_700_000.0)


class Ham(unittest.TestCase):
    def setUp(self):
        from ham_helpers import make_radio as ham_radio
        self.ham_radio = ham_radio
        self.radios = []

    def tearDown(self):
        from ham_helpers import close
        for r in self.radios:
            close(r)

    def radio(self, **over):
        r = self.ham_radio(**over)
        self.radios.append(r)
        return r

    def test_ft8_on_20m_lands_on_its_dial_and_stays_on_the_band(self):
        r = self.radio(vfo=14_200_000.0, mode="usb")
        r.set_mode_tuned("ft8")
        s = r.state()
        self.assertEqual(s["mode"], "ft8")
        self.assertEqual(s["vfo"], 14_074_000.0)
        self.assertEqual(bands.band_at(s["vfo"]).name, "20m")


if __name__ == "__main__":
    unittest.main()
