"""Receive is never disturbed (Brian, 17/10/2026, after NB's Mac test:
a resize, a theme toggle or a dialog each cost a receive overrun, and a
recording blamed the disk for a stalled link to the Pluto).

In real time, against tools/rx_storm.py's paced simulator: the NB signal
delivered as a Pluto's DMA delivers it, into four 75 ms kernel buffers and
lost beyond them - so a receive thread that comes back late loses samples
here exactly as it would on the radio. Nothing transmits; the simulator
radiates nothing anyway."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from helpers import make_radio
from ohscore import sigmf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_spec = importlib.util.spec_from_file_location(
    "rx_storm", Path(__file__).resolve().parent.parent / "tools" / "rx_storm.py")
rx_storm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rx_storm)

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


def pump(seconds, radio, app=None, feeds=()):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if app is not None:
            app.processEvents()
        radio.heartbeat()
        for f in feeds:
            f.drain()
        time.sleep(0.01)


class EngineReadsAhead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radio = make_radio(self.tmp, device=rx_storm.paced_device(loop_s=2.0), vfo=10_489_700_000.0)
        self.radio.start()
        self.feeds = [self.radio.subscribe(k, 64) for k in ("toast", "state", "wide", "zoom")]
        pump(2.0, self.radio, feeds=self.feeds)

    def tearDown(self):
        self.radio.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_starved_receive_thread_loses_nothing_and_says_late_not_overrun(self):
        r, dev = self.radio, self.radio.dev
        orig, stalled = r._rx_block, []

        def block(x):
            if not stalled:
                stalled.append(1)
                time.sleep(1.0)      # a second with no share of the GIL
            orig(x)
        r._rx_block = block
        pump(3.0, r, feeds=self.feeds)
        self.assertTrue(stalled)
        self.assertEqual(dev.lost, 0)
        self.assertEqual(r.overruns, 0)
        self.assertGreaterEqual(r.rx_late, 1)
        st = r.state()
        self.assertEqual(st["overruns"], 0)
        self.assertGreaterEqual(st["rxLate"], 1)

    def test_a_stalled_link_is_an_overrun_and_the_recording_blames_the_stream(self):
        r, dev = self.radio, self.radio.dev
        path = r.start_recording(folder=Path(self.tmp) / "rec")
        pump(0.5, r, feeds=self.feeds)
        dev.stall(1.0)                   # 0.7 s more than the kernel buffers hold
        pump(5.0, r, feeds=self.feeds)   # the loss is known once the stream has settled (rxprefetch window_s)
        toasts = []
        r.stop_recording()
        deadline = time.monotonic() + 10
        while r.rec_closing and time.monotonic() < deadline:
            r.heartbeat()
            toasts += [it["text"] for it in self.feeds[0].drain()]
            time.sleep(0.02)
        toasts += [it["text"] for it in self.feeds[0].drain()]
        self.assertAlmostEqual(dev.lost / dev.fs, 0.7, delta=0.1)
        self.assertGreaterEqual(r.overruns, 1)
        self.assertAlmostEqual(r.rx_lost / dev.fs, dev.lost / dev.fs, delta=0.25)
        m = json.loads(sigmf.paths(path)[1].read_text())
        g = m["global"]
        self.assertEqual(g["openhamshack:dropped_samples"], 0)            # not the disk
        self.assertGreater(g["openhamshack:rx_lost_samples"], 0)
        gaps = [c for c in m["captures"] if "openhamshack:gap_samples" in c]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["openhamshack:gap_samples"], g["openhamshack:rx_lost_samples"])
        said = " ".join(toasts)
        self.assertIn("never arrived from the radio", said)
        self.assertNotIn("disk could not keep up", said)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class WindowStorm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        self.radio = make_radio(self.tmp, device=rx_storm.paced_device(loop_s=2.0), vfo=10_489_540_000.0)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        prefs["theme"] = "dark"
        self.win, self.bridge = build(self.radio, prefs)
        self.win.resize(1600, 960)
        self.win.show()
        pump(2.0, self.radio, self.app)

    def tearDown(self):
        self.win.close()
        self.bridge.stop()
        self.app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_ui_storm_costs_receive_nothing(self):
        # What cost the Mac an overrun each, and more: two theme toggles
        # (1.4-2.4 s of GUI thread each, before), resizes, dish alignment.
        w, r = self.win, self.radio
        w.set_theme("light")
        w.resize(1000, 640)
        self.app.processEvents()
        w.set_theme("dark")
        w.resize(1600, 960)
        d = w.open_dish()
        self.app.processEvents()
        if d is not None:
            d.close()
        pump(2.0, r, self.app)
        self.assertEqual(r.dev.lost, 0)
        self.assertEqual(r.overruns, 0)

    def test_a_theme_change_keeps_the_band_activity_the_text_and_the_waterfall(self):
        from ohscore.ui import theme
        w = self.win
        w.set_mode("ft8")
        pump(1.5, self.radio, self.app)
        slot = float(int(time.time() // 15) * 15)
        for i, text in enumerate(("CQ DL1ABC JO62", "G4XYZ DL1ABC -07", "CQ OH8ZZ KP20")):
            w.on_event({"mode": "ft8", "text": text, "slot": slot, "snr": -7 - i, "dt": 0.1, "df": 800 + 100 * i,
                        "call": text.split()[1]})
        w._ensure_panel("text").term.put("CQ CQ DE G4XYZ", "rx")
        rows_before = w.panels["slot"].table.rowCount()
        texts = [w.panels["slot"].table.item(rr, 5).text() for rr in range(rows_before)
                 if w.panels["slot"].table.item(rr, 5) is not None]
        lines_before = w.wide.wf.rows_total
        self.assertGreater(lines_before, 10)

        w.set_theme("light")
        pump(0.5, self.radio, self.app)
        t = w.panels["slot"].table
        self.assertEqual(t.rowCount(), rows_before)
        self.assertEqual([t.item(rr, 5).text() for rr in range(t.rowCount()) if t.item(rr, 5) is not None], texts)
        # Replayed in this theme's colours: the CQ row's text is light-theme text.
        cq_row = next(rr for rr in range(t.rowCount()) if t.item(rr, 5) and t.item(rr, 5).text().startswith("CQ DL1"))
        self.assertEqual(t.item(cq_row, 5).foreground().color().name(), theme.c("text").name())
        self.assertIn("CQ CQ DE G4XYZ", [h[0] for h in w.panels["text"].term.history])
        self.assertGreaterEqual(w.wide.wf.rows_total, lines_before)
        # Nothing a decode sets going was replayed: transmit stays off.
        self.assertFalse(w.panels["slot"].tx_enabled)


if __name__ == "__main__":
    unittest.main()
