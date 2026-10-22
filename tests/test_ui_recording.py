"""File › Record receive IQ… in the window (ohscore/ui/recording.py), against
a real Radio on the simulator, on Qt's offscreen platform: the dialog says
the cost before anything is written, Record starts the engine's recording,
the status strip and the menu item show it, and the menu item stops it -
as do a time limit, with the menu following."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import time
import unittest

from test_ui_window import HAVE_QT, WindowCase


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class RecordFromTheWindow(WindowCase):
    def until_saved(self, radio, timeout=10.0):
        t0 = time.monotonic()
        while (radio.rec_closing or radio.state()["recording"]) and time.monotonic() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.01)
        self.run_for(radio, until=lambda: False, timeout=0.3)      # the state feed reaches the window

    def test_record_and_stop_from_the_menu(self):
        from ohscore.ui import recording
        win, bridge, radio = self.window()
        self.run_for(radio, until=lambda: radio.state()["running"])
        self.assertEqual(win.act_rec.text(), "Record receive IQ…")
        d = recording.RecordDialog(win)
        # The cost, the free space and the place, before anything is written.
        self.assertIn("288 MB a minute", d.cost.text())
        self.assertIn("free there", d.cost.text())
        self.assertTrue(d.where.text().endswith("recordings"))
        self.assertFalse(radio.recordings_dir().exists() and any(radio.recordings_dir().iterdir()))
        self.assertTrue(d.record())
        self.assertTrue(radio.state()["recording"])
        self.assertTrue(win.act_rec.isChecked())
        self.assertEqual(win.act_rec.text(), "Stop recording")
        self.run_for(radio, sim_s=1.5)
        self.run_for(radio, until=lambda: (bridge.st.get("recBytes") or 0) > 0, timeout=5)
        self.assertTrue(recording.rec_status(bridge.st).startswith("● REC 0:0"))
        from ohscore import sigmf
        self.assertTrue(recording.rec_status(bridge.st).endswith(sigmf.size_text(bridge.st["recBytes"])))
        # The same menu item stops it.
        win.act_rec.trigger()
        self.assertFalse(radio.state()["recording"])
        self.until_saved(radio)
        self.assertFalse(win.act_rec.isChecked())
        self.assertEqual(win.act_rec.text(), "Record receive IQ…")
        self.assertEqual(recording.rec_status(bridge.st), "")
        files = sorted(p.suffix for p in radio.recordings_dir().iterdir())
        self.assertEqual(files, [".sigmf-data", ".sigmf-meta"])

    def test_a_time_limit_ends_it_and_the_menu_follows(self):
        from ohscore.ui import recording
        win, bridge, radio = self.window()
        self.run_for(radio, until=lambda: radio.state()["running"])
        d = recording.RecordDialog(win)
        d.limit.setValue(2)
        self.assertTrue(d.record())
        self.assertEqual(radio.state()["recLimitMin"], 2.0)        # remembered for next time
        win.act_rec.trigger()
        self.until_saved(radio)
        self.assertEqual(recording.RecordDialog(win).limit.value(), 2)
        # A limit ends it with nobody at the menu, and the menu follows. (A
        # second's limit straight to the engine: two minutes of IQ would be
        # 580 MB of test file.)
        radio.start_recording(limit_s=1.0)
        self.run_for(radio, until=lambda: win.act_rec.isChecked(), timeout=5)
        self.run_for(radio, sim_s=1.5, timeout=30)
        self.until_saved(radio)
        self.assertFalse(win.act_rec.isChecked())
        self.assertEqual(win.act_rec.text(), "Record receive IQ…")

    def test_refused_when_the_radio_is_stopped(self):
        from ohscore.ui import recording
        win, bridge, radio = self.window()
        self.run_for(radio, until=lambda: radio.state()["running"])
        radio.stop()
        d = recording.RecordDialog(win)
        self.assertFalse(d.record())
        self.assertIn("Start the radio", d.result_label.text())


if __name__ == "__main__":
    unittest.main()
