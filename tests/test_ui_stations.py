"""Radio's desktop window for broadcast listening (ohsradio/ui/broadcast.py),
driven as an operator would on the RSPdx-shaped simulator with shack_sdr's
FM stereo and RDS transmitter and its DAB ensemble on the air:

- **By the frequency:** in wide FM the station's name large, STEREO while
  its pilot is heard, its RadioText as what is on now; nothing in other
  modes.
- **Stations:** Scan now fills the FM list; it sorts by name or by
  frequency and filters by programme type; a click tunes to a programme's
  strongest frequency in wide FM. The DAB list shows each service with its
  ensemble and block; a click starts the DAB session for it, and another
  service on the same block switches that session.
- **Now playing (DAB):** under the list while a DAB station plays, its
  name, its DL Plus title and artist, the guide's programme and genre, its
  logo and its latest slide, all off the simulated ensemble's air; the
  list then shows the logo beside the station and its programme type.

Nothing here keys."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ohscore import sdr

from listen_helpers import make_listener


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class BroadcastWindow(unittest.TestCase):
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
        for win, bridge, r in self.wins:
            win.close()
            bridge.stop()
            r._tmp.cleanup()
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
        from ohsradio.devices.simdab import DabEnsemble
        from ohsradio.devices.simfm import BAND, FmBand
        from ohsradio.ui import build
        r, _audio, dev = make_listener([], **{"vfo": 88_600_000.0, "mode": "wfm", **over})
        dev.fm = FmBand(list(BAND))
        dev.dab = DabEnsemble("11D", level_db=-30.0)
        r.bandscan.fm_lo, r.bandscan.fm_hi = 88_000_000, 95_000_000
        r.bandscan.dab_blocks = ["11D"]
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(r, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge, r))
        self.settle_until(lambda: r.state()["running"])
        return win, bridge, r

    def settle_until(self, cond, sec=30.0):
        end = time.monotonic() + sec
        while not cond() and time.monotonic() < end:
            self.app.processEvents()
            for _w, _b, r in self.wins:
                r.heartbeat()
            time.sleep(0.01)
        return cond()

    def test_the_station_by_the_frequency(self):
        win, bridge, r = self.window()
        strip = win.rds_strip
        self.assertTrue(self.settle_until(lambda: strip.ps.text() == "SIM ONE" and strip.badge.isVisible()))
        self.assertTrue(strip.isVisible())
        self.assertIn("PI C201", strip.toolTip())
        self.assertIn("Pop music", strip.toolTip())
        self.assertTrue(self.settle_until(lambda: strip.rt_full != "", 60))
        self.assertEqual(strip.rt_full, "Now: Sim One: 1 kHz left, 1.5 right")
        # Another mode: nothing.
        bridge.set(mode="usb", vfo=14_074_000.0)
        self.assertTrue(self.settle_until(lambda: not strip.isVisible()))
        self.assertEqual(strip.ps.text(), "")

    def rows(self, view):
        t = view.tree
        return [tuple(t.topLevelItem(i).text(c) for c in range(t.columnCount())) for i in range(t.topLevelItemCount())]

    def test_scan_now_sort_filter_and_tune(self):
        win, bridge, r = self.window(mode="usb", vfo=14_074_000.0)
        win.show_view("stations")
        view = win.stations_view
        self.assertIn("No FM stations listed yet", view.status.text())
        view.scan_now()
        self.assertFalse(view.scan_btn.isEnabled())
        # Listed, and the scan over: the button is back.
        self.assertTrue(self.settle_until(lambda: view.tree.topLevelItemCount() == 2 and view.scan_btn.isEnabled(),
                                          300), view.status.text())
        self.assertEqual([row[0] for row in self.rows(view)], ["SIM ONE", "SIMNEWS"])
        self.assertEqual(self.rows(view)[0][3], "91.3\xa0MHz")                 # its alternative
        view.sort.setCurrentIndex(view.sort.findData("freq"))
        self.assertEqual([row[1] for row in self.rows(view)], ["88.6\xa0MHz", "93.5\xa0MHz"])
        view.genre.setCurrentIndex(view.genre.findData("News"))
        self.assertEqual([row[0] for row in self.rows(view)], ["SIMNEWS"])
        self.assertEqual(win.prefs["stationsSort"], "freq")
        # A click tunes there, in wide FM.
        view.tree.itemClicked.emit(view.tree.topLevelItem(0), 0)
        st = r.state()
        self.assertEqual((st["mode"], st["vfo"]), ("wfm", 93_500_000.0))

    def test_a_dab_service_plays_and_switches(self):
        win, bridge, r = self.window(mode="fm", vfo=145_500_000.0)
        win.show_view("stations")
        view = win.stations_view
        view.band.setCurrentIndex(view.band.findData("dab"))
        view.scan_now()
        self.assertTrue(self.settle_until(lambda: view.tree.topLevelItemCount() == 2, 300), view.status.text())
        rows = self.rows(view)
        self.assertEqual([row[:2] for row in rows], [("Shack DAB+ Data", "Shack Test Mux"),
                                                     ("Shack MP2 Tone", "Shack Test Mux")])
        self.assertTrue(rows[1][2].startswith("11D"))
        self.assertEqual(rows[1][3], "DAB 128 kbit/s")
        view.tree.itemClicked.emit(view.tree.topLevelItem(1), 0)
        (sess,) = [s for s in r.decoders.sessions() if s.get("holdsReceiver")]
        self.assertEqual((sess["block"], sess["params"]["service"]), ("11D", "C221"))
        view.tree.itemClicked.emit(view.tree.topLevelItem(0), 0)
        (again,) = [s for s in r.decoders.sessions() if s.get("holdsReceiver")]
        self.assertEqual((again["id"], again["params"]["service"]), (sess["id"], "C3A7"))
        # And an FM programme from there: the DAB station stops, the dial goes there.
        view.band.setCurrentIndex(view.band.findData("fm"))
        self.assertTrue(view.tune_fm(88_600_000.0))
        self.assertEqual([s for s in r.decoders.sessions() if s.get("holdsReceiver")], [])
        self.assertEqual((r.state()["mode"], r.state()["vfo"]), ("wfm", 88_600_000.0))

    def test_the_playing_dab_station_shows_its_slide_logo_and_what_is_on(self):
        from shack_sdr import _native
        try:
            _native.testsig_dab(1, showcase_mjd=61_337)
        except TypeError:
            self.skipTest("shack_sdr without the showcase ensemble")
        win, bridge, r = self.window(mode="fm", vfo=145_500_000.0)
        win.show_view("stations")
        view = win.stations_view
        view.band.setCurrentIndex(view.band.findData("dab"))
        self.assertFalse(view.playing.isVisible())
        view.play_dab("11D", 222_064_000.0, "C221")
        p = view.playing
        self.assertTrue(self.settle_until(lambda: p.isVisible() and p.slide.pixmap() is not None
                                          and not p.slide.pixmap().isNull() and not p.logo.pixmap().isNull()
                                          and p.on_now.text().startswith("On now:"), 120),
                        (p.name.text(), p.what.text(), p.on_now.text()))
        self.assertEqual(p.name.text(), "Shack MP2 Tone")
        self.assertEqual(p.what.text(), "1 kHz left by Shack MP2 Tone")
        self.assertIn("Pop music", p.on_now.text())
        # The list, filled from a scan's record, shows the logo and the type.
        from ohsradio.bandscan import dab_ensemble
        (sess,) = [s for s in r.decoders.sessions() if s.get("holdsReceiver")]
        meta = r.decoders.session(sess["id"])["meta"]
        r.bandscan.records["dab"]["ensembles"] = [dab_ensemble("11D", 222_064_000.0, meta)]
        view.refresh()
        rows = {view.tree.topLevelItem(i).text(0): view.tree.topLevelItem(i) for i in range(view.tree.topLevelItemCount())}
        self.assertFalse(rows["Shack MP2 Tone"].icon(0).isNull())
        self.assertEqual(rows["Shack MP2 Tone"].text(4), "Pop music")
        # Stopped: the panel goes.
        r.decoders.stop(sess["id"])
        self.assertTrue(self.settle_until(lambda: not p.isVisible(), 10))


if __name__ == "__main__":
    unittest.main()
