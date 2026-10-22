"""File › Play IQ recording… in the window (ohscore/ui/playback.py), against a
real Radio on the simulator, on Qt's offscreen platform: a recording plays
in place of the radio, the status strip says PLAYBACK where the radio's
name stood, transmit says why it is off, recording is not offered, and the
same menu item goes back to the radio."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import time
import unittest
from pathlib import Path
from unittest import mock

from test_ui_window import HAVE_QT, WindowCase


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class PlayFromTheWindow(WindowCase):
    def recorded(self, radio, seconds=0.6) -> Path:
        self.run_for(radio, until=lambda: radio.state()["running"])
        path = radio.start_recording(limit_s=seconds)
        self.run_for(radio, until=lambda: not radio.state()["recording"] and not radio.rec_closing, timeout=20)
        return path

    def test_play_and_back_from_the_menu(self):
        from ohscore.ui import playback
        win, bridge, radio = self.window()
        path = self.recorded(radio)
        self.assertEqual(win.act_play.text(), "Play IQ recording…")
        with mock.patch.object(playback.QFileDialog, "getOpenFileName", return_value=(str(path), "")):
            win.act_play.trigger()
        self.assertTrue(radio.state()["playing"])
        self.assertEqual(radio.dev.kind, "file")
        self.assertTrue(win.act_play.isChecked())
        self.assertEqual(win.act_play.text(), "Back to the radio")
        self.assertFalse(win.act_rec.isEnabled())
        self.run_for(radio, until=lambda: (bridge.st.get("playPos") or 0) > 0.2, timeout=10)
        text = playback.play_status(bridge.st)
        self.assertTrue(text.startswith("▶ PLAYBACK  " + path.name[:-len(".sigmf-data")] + "  0:00 / 0:00"), text)
        self.assertIn("recorded ", text)
        self.assertIn("Playing a recording", bridge.can_key())
        win.status.repaint()                                     # the strip paints it without complaint
        self.run_for(radio, until=lambda: bridge.st.get("playEnded"), timeout=10)
        self.assertTrue(playback.play_status(bridge.st).endswith("(ended)"))
        # The same item goes back to the radio.
        win.act_play.trigger()
        self.assertFalse(radio.state()["playing"])
        self.assertEqual(radio.dev.kind, "sim")
        self.assertFalse(win.act_play.isChecked())
        self.assertEqual(win.act_play.text(), "Play IQ recording…")
        self.assertTrue(win.act_rec.isEnabled())
        self.assertEqual(playback.play_status(bridge.st), "")
        self.run_for(radio, until=lambda: bridge.st.get("canTx"), timeout=5)
        self.assertEqual(bridge.can_key(), bridge.st.get("txBlocked", ""))

    def test_loop_is_a_menu_tick_and_a_cancelled_choice_changes_nothing(self):
        from ohscore.ui import playback
        win, bridge, radio = self.window()
        self.run_for(radio, until=lambda: radio.state()["running"])
        win.act_loop.trigger()
        self.assertTrue(radio.state()["playLoop"])
        with mock.patch.object(playback.QFileDialog, "getOpenFileName", return_value=("", "")):
            win.act_play.trigger()
        self.assertFalse(radio.state()["playing"])
        self.assertFalse(win.act_play.isChecked())

    def test_a_file_that_cannot_be_played_is_a_toast_and_the_radio_carries_on(self):
        from ohscore.ui import playback
        win, bridge, radio = self.window()
        self.run_for(radio, until=lambda: radio.state()["running"])
        said = []
        bridge.toast.connect(lambda t: said.append(t["text"]))
        self.assertFalse(playback.play(win, Path(self.tmp) / "nothing.sigmf-meta"))
        self.assertTrue(any("missing" in s for s in said), said)
        self.assertTrue(radio.state()["running"])
        self.assertEqual(radio.dev.kind, "sim")
        self.assertFalse(win.act_play.isChecked())


if __name__ == "__main__":
    unittest.main()
