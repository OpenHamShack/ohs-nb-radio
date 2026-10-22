"""Radio's CW Activity view (ohscore/ui/cwskimview.py, wired in
ohsradio/ui/mainwindow.py): the store that follows the cwskim/cwspot feeds,
and the window driven as an operator would on the band simulator.

The store keeps spots by id per skimmer run, refetches the whole list on a
gap in `rev`, keeps each channel's text across the server's 48-character
windows, and lists no busted call. The window's switch is the engine's
`cwSkim`; a click on a spot, a signal or a mark on the scope tunes the dial
to it in CW, and nothing in it keys."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from ham_helpers import make_radio


def spot(sid, call, f, status="valid", kind="cq", last=None, band="20m", **kw):
    now = time.time() if last is None else last
    return {"id": sid, "call": call, "f": f, "dial": f - 700.0, "mode": "cw", "wpm": 24.0, "snr": 18.0,
            "kind": kind, "status": status, "hits": 2, "first": now - 30, "last": now, "band": band,
            "channel": 1, "country": "Sweden", "dxcc": "SM", "continent": "EU", **kw}


def item(state="running", channels=(), rev=0, band="20m"):
    return {"t": time.time(), "state": state, "band": band,
            "segment": {"lo": 14_000_000.0, "hi": 14_070_000.0, "plan": "rsgb-2026"},
            "cover": {"lo": 14_000_000.0, "hi": 14_070_000.0}, "spotsRev": rev,
            "channels": list(channels), "carriers": []}


class Text(unittest.TestCase):
    def test_merge_runs_on_from_the_overlap(self):
        from ohscore.ui.cwskimview import merge_text
        self.assertEqual(merge_text("", "CQ CQ DE SM5D"), "CQ CQ DE SM5D")
        self.assertEqual(merge_text("CQ CQ DE SM5D", "CQ DE SM5D SM5D K"), "CQ CQ DE SM5D SM5D K")
        # Nothing new: the same window again.
        self.assertEqual(merge_text("CQ CQ DE SM5D SM5D K", "SM5D K"), "CQ CQ DE SM5D SM5D K")

    def test_a_short_text_that_overlaps_nothing_is_a_new_channel(self):
        from ohscore.ui.cwskimview import merge_text
        self.assertEqual(merge_text("CQ CQ DE SM5D", "OK1FAV"), "OK1FAV")
        # A whole window with no overlap printed more than a window since:
        # kept after a space rather than dropped.
        full = "X" * 47 + "Y"
        self.assertEqual(merge_text("ABC", full), "ABC " + full)

    def test_kept_text_is_bounded(self):
        from ohscore.ui.cwskimview import TEXT_KEEP, merge_text
        t = ""
        for i in range(200):
            t = merge_text(t, (t + f" {i:03d}")[-48:])
        self.assertEqual(len(t), TEXT_KEEP)
        self.assertTrue(t.endswith(" 199"))


if HAVE_QT:
    class FakeFeed:
        def __init__(self, kind):
            self.kind, self.items = kind, []

        def drain(self):
            out, self.items = self.items, []
            return out

    class FakeRadio:
        def __init__(self, view):
            self.view, self.asked = view, 0
            self.feeds = {}

        def subscribe(self, kind, n=64):
            self.feeds[kind] = FakeFeed(kind)
            return self.feeds[kind]

        def cwskim_view(self):
            self.asked += 1
            return self.view

    class FakeBridge(QObject):
        tick = pyqtSignal(float)
        changed = pyqtSignal(dict)

        def __init__(self, radio, st=None):
            super().__init__()
            self.radio, self.st = radio, dict(st or {"cwSkim": True, "cwSkimState": "running"})


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Store(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def store(self, spots=(), rev=0, **st):
        from ohscore.ui.cwskimview import CwSkimStore
        view = dict(item(rev=rev), spots=list(spots))
        radio = FakeRadio(view)
        bridge = FakeBridge(radio, {"cwSkim": True, "cwSkimState": "running", **st})
        s = CwSkimStore(bridge)
        return s, radio, bridge

    def send(self, radio, *spots, snap=None, rev0=None):
        for i, sp in enumerate(spots):
            radio.feeds["cwspot"].items.append({"t": time.time(), "rev": sp.pop("_rev"), "spot": sp})
        if snap is not None:
            radio.feeds["cwskim"].items.append(snap)

    def test_fills_from_the_view_and_lists_no_busted_call(self):
        s, radio, _ = self.store([spot(3, "SM5D", 14_025_210.0), spot(2, "S2RW", 14_013_090.0, status="busted"),
                                  spot(1, "OK1FAV", 14_015_510.0, status="unconfirmed", kind="dx")], rev=3)
        self.assertEqual(radio.asked, 1)
        self.assertEqual([x["call"] for x in s.shown()], ["OK1FAV", "SM5D"])          # by frequency
        self.assertEqual(s.rev, 3)

    def test_newest_first_on_asking(self):
        t = time.time()
        s, _, _ = self.store([spot(1, "SM5D", 14_025_210.0, last=t - 60), spot(2, "OK1FAV", 14_015_510.0, last=t)])
        self.assertEqual([x["call"] for x in s.shown("new")], ["OK1FAV", "SM5D"])

    def test_a_spot_sent_again_replaces_itself_and_is_labelled_once_confirmed(self):
        s, radio, _ = self.store()
        said = []
        s.spotted.connect(said.append)
        self.send(radio, dict(spot(5, "EA7LS", 14_016_500.0, status="unconfirmed"), _rev=1))
        s.pump()
        self.assertEqual(said, [])
        self.send(radio, dict(spot(5, "EA7LS", 14_016_500.0, hits=2), _rev=2))
        s.pump()
        self.send(radio, dict(spot(5, "EA7LS", 14_016_500.0, hits=3), _rev=3))
        s.pump()
        self.assertEqual([x["call"] for x in said], ["EA7LS"])
        self.assertEqual(len(s.spots), 1)
        self.assertEqual(radio.asked, 1)       # no gap, no refetch

    def test_a_gap_in_rev_fetches_the_whole_list_again(self):
        s, radio, _ = self.store()
        self.send(radio, dict(spot(1, "SM5D", 14_025_210.0), _rev=1))
        s.pump()
        self.send(radio, dict(spot(4, "RD9D", 14_013_200.0), _rev=4))
        s.pump()
        self.assertEqual(radio.asked, 2)
        # And a snapshot that names a newer rev than any spot seen.
        self.send(radio, snap=item(rev=9))
        s.pump()
        self.assertEqual(radio.asked, 3)

    def test_a_skimmer_started_again_is_a_new_run(self):
        s, radio, _ = self.store()
        self.send(radio, dict(spot(1, "SM5D", 14_025_210.0), _rev=1), dict(spot(2, "9A3ST", 14_016_200.0), _rev=2))
        s.pump()
        # Off and on: the new worker numbers its spots from 1 again.
        self.send(radio, dict(spot(1, "OK1FAV", 14_015_510.0), _rev=1))
        s.pump()
        self.assertEqual(sorted(x["call"] for x in s.shown()), ["9A3ST", "OK1FAV", "SM5D"])
        self.assertEqual(s.rev, 1)

    def test_clear_empties_the_list_and_new_spots_come_back(self):
        t = time.time()
        s, radio, _ = self.store([spot(1, "SM5D", 14_025_210.0, last=t - 5)])
        s.clear()
        self.assertEqual(s.shown(), [])
        self.send(radio, dict(spot(2, "RD9D", 14_013_200.0, last=time.time() + 1), _rev=1))
        s.pump()
        self.assertEqual([x["call"] for x in s.shown()], ["RD9D"])

    def test_channel_text_runs_on_across_snapshots(self):
        s, radio, _ = self.store()
        ch = {"id": 17, "f": 14_015_511.2, "dial": 14_014_811.2, "wpm": 24.0, "snr": 28.8, "active": True,
              "decoding": True}
        self.send(radio, snap=item(channels=[dict(ch, text="5NN E OK1FAV OK1FAV")]))
        s.pump()
        self.send(radio, snap=item(channels=[dict(ch, text="OK1FAV OK1FAV 5NN TU")]))
        s.pump()
        self.assertEqual(s.texts[17], "5NN E OK1FAV OK1FAV 5NN TU")
        self.send(radio, snap=item(channels=[]))
        s.pump()
        self.assertNotIn(17, s.texts)

    def test_marks_are_the_dial_band_spots_while_it_runs(self):
        t = time.time()
        s, _, bridge = self.store([spot(1, "SM5D", 14_025_210.0), spot(2, "W1AW", 7_025_000.0, band="40m"),
                                   spot(3, "RD9D", 14_013_200.0, last=t - 900),
                                   spot(4, "OK1FAV", 14_015_510.0, status="unconfirmed", kind="dx")])
        marks = s.marks(t)
        self.assertEqual([m["text"] for m in marks], ["OK1FAV", "SM5D"])
        self.assertEqual([m["active"] for m in marks], [False, True])
        self.assertEqual(marks[1]["colour"], "cq")
        self.assertAlmostEqual(marks[1]["lo"], 14_025_150.0)
        s.item = dict(s.item, state="off")
        self.assertEqual(s.marks(t), [])

    def test_status_says_off_outside_and_running(self):
        from ohscore.ui.cwskimview import status_text
        self.assertIn("Switch it on", status_text({"cwSkim": False}, {"state": "off"}))
        why = "The CW segment, 28.000-28.070 MHz, is outside what the receiver covers now."
        self.assertEqual(status_text({"cwSkim": True, "cwSkimState": "outside", "cwSkimWhy": why}, {}), why)
        line = status_text({"cwSkim": True, "cwSkimState": "running", "cwSkimSignals": 12, "cwSkimChannels": 9,
                            "cwSkimCpu": 21.5}, item())
        self.assertIn("20m CW 14.000–14.070 MHz", line)
        self.assertIn("12 signals", line)
        self.assertIn("9 decoding", line)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Window(unittest.TestCase):
    """Radio's window on the simulator. The skimmer runs in a thread here
    (Radio.CWSKIM_MODE); spots are published on the engine's own feeds as
    the skimmer publishes them, so the list's contents are the test's."""

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
        radio = make_radio(**{"vfo": 14_060_000.0, "mode": "usb", **over})
        radio.CWSKIM_MODE = "thread"
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.settle(0.3)
        return win, bridge, radio

    def settle(self, sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def settle_until(self, cond, sec=5.0):
        end = time.monotonic() + sec
        while not cond() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        return cond()

    def test_the_view_is_offered_and_its_switch_is_cwskim(self):
        win, bridge, radio = self.window()
        self.assertIn("cwskim", win.extra_views)
        win.show_view("cwskim")
        view = win.cwskim_view
        self.assertFalse(radio.st["cwSkim"])
        self.assertFalse(view.onoff.on)
        self.assertIn("Switch it on", view.status.text())
        view.onoff.set_on(True, emit=True)
        self.assertTrue(radio.st["cwSkim"])
        self.assertTrue(self.settle_until(lambda: radio.state().get("cwSkimState") in ("running", "partial")))
        view.onoff.set_on(False, emit=True)
        self.assertFalse(radio.st["cwSkim"])
        # Changed elsewhere (Settings, a Remote): the switch follows.
        bridge.set(cwSkim=True)
        self.settle(0.1)
        self.assertTrue(view.onoff.on)
        bridge.set(cwSkim=False)

    def publish(self, radio, sp, rev):
        radio._publish("cwspot", {"t": time.time(), "rev": rev, "spot": sp})

    def test_a_click_on_a_spot_tunes_there_in_cw_and_keys_nothing(self):
        win, bridge, radio = self.window()
        win.show_view("cwskim")
        view = win.cwskim_view
        self.publish(radio, spot(1, "SM5D", 14_025_213.0), 1)
        self.publish(radio, spot(2, "S2RW", 14_013_090.0, status="busted"), 2)
        self.assertTrue(self.settle_until(lambda: view.spot_table.rowCount() == 1))
        self.assertEqual(view.spot_table.item(0, 2).text(), "SM5D")
        self.assertEqual(view.spot_table.item(0, 1).text(), "14025.21")
        self.assertEqual(view.spot_table.item(0, 5).text(), "Sweden")
        self.assertEqual(view.spot_table.item(0, 6).text(), "CQ")
        view.spot_table.cellClicked.emit(0, 2)
        self.settle(0.1)
        st = radio.state()
        self.assertEqual(st["mode"], "cw")
        # The signal less the CW pitch, on the 10 Hz grid a scope click uses.
        self.assertEqual(st["vfo"], 14_024_510.0)
        self.assertFalse(st["keyed"])

    def test_a_mark_on_the_wide_scope_tunes_and_new_calls_are_labelled(self):
        win, bridge, radio = self.window()
        radio._status(cwSkimState="running")
        radio._publish("cwskim", item())
        self.publish(radio, spot(1, "RD9D", 14_013_200.0, kind="dx"), 1)
        self.assertTrue(self.settle_until(lambda: any(m["text"] == "RD9D" for m in win.wide.band_marks)))
        self.assertTrue(any(lab["text"] == "RD9D" for lab in win.wide.labels))
        mark = next(m for m in win.wide.band_marks if m["text"] == "RD9D")
        win.wide.mark_clicked.emit(mark)
        self.settle(0.1)
        self.assertEqual((radio.state()["mode"], radio.state()["vfo"]), ("cw", 14_012_500.0))
        # Marks off: none on the scope.
        win.cwskim_view.marks_on.set_on(False, emit=True)
        self.assertEqual(win.wide.band_marks, [])

    def test_the_signals_list_shows_each_channel_text(self):
        win, bridge, radio = self.window()
        win.show_view("cwskim")
        view = win.cwskim_view
        view.tabs.picked.emit("signals")
        ch = {"id": 17, "f": 14_015_511.2, "dial": 14_014_811.2, "wpm": 24.0, "snr": 28.8, "active": True,
              "decoding": True, "call": "OK1FAV", "kind": "dx", "first": time.time()}
        radio._publish("cwskim", item(channels=[dict(ch, text="5NN E OK1FAV OK1FAV")]))
        self.assertTrue(self.settle_until(lambda: view.chan_table.rowCount() == 1))
        radio._publish("cwskim", item(channels=[dict(ch, text="OK1FAV OK1FAV 5NN TU")]))
        self.assertTrue(self.settle_until(lambda: view.chan_table.item(0, 4).text().endswith("5NN TU")))
        self.assertEqual(view.chan_table.item(0, 4).text(), "5NN E OK1FAV OK1FAV 5NN TU")
        self.assertEqual(view.chan_table.item(0, 3).text(), "OK1FAV")
        view.chan_table.cellClicked.emit(0, 4)
        self.settle(0.1)
        self.assertEqual((radio.state()["mode"], radio.state()["vfo"]), ("cw", 14_014_810.0))

    def test_settings_offer_the_three_keys(self):
        win, bridge, radio = self.window()
        dlg = win.settings_dialog()
        try:
            for key in ("cwSkim", "cwSkimSquelch", "cwSkimMax"):
                self.assertIn(key, dlg.fields, key)
        finally:
            dlg.close()


class Selftest(unittest.TestCase):
    def test_the_selftest_spots_every_station_in_a_worker_process(self):
        # What the frozen builds run (--cw-skim-selftest): the child process
        # is real here too, so a break in starting it shows on Linux first.
        from ohsradio.cwskim import selftest
        said = []
        self.assertEqual(selftest(said.append), 0, "\n".join(said))
        self.assertTrue(any("worker process pid" in s for s in said), said)
        self.assertIn("cw-skim-selftest: PASS", said)


if __name__ == "__main__":
    unittest.main()
