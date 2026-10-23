"""Radio's Local view and Settings › Local frequencies (ohsradio/ui/
localview.py, wired in ohsradio/ui/mainwindow.py and ohsradio/ui/
settings.py), driven as an operator would on the band simulator: the view
lists what is near the locator with its attributions, a category narrows
it, a click tunes the dial, mode and step, and the operator's own list is
added to, edited and deleted from Settings and shows in the view. Nothing
here keys or reaches the network."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ham_helpers import make_radio


class LocalWindow(unittest.TestCase):
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
        radio = make_radio(**{"locator": "IO75TU", "localRadiusKm": 60, "vfo": 14_070_000.0, "mode": "usb",
                              **over})
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.settle_until(lambda: radio.state()["running"])
        return win, bridge, radio

    def settle_until(self, cond, sec=5.0):
        end = time.monotonic() + sec
        while not cond() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)
        return cond()

    def cells(self, view, row):
        return [view.table.item(row, c).text() for c in range(view.table.columnCount())]

    def test_the_view_lists_near_things_and_a_click_tunes(self):
        win, bridge, radio = self.window()
        self.assertIn("local", win.extra_views)
        win.show_view("local")
        view = win.local_view
        names = [e["name"] for e in view.rows]
        self.assertIn("Glasgow Airport", names)
        self.assertIn("within 60 km of IO75TU", view.radius.text())
        self.assertIn("OurAirports", view.credits.text())
        view.cat.setCurrentIndex(view.cat.findData("marine"))
        self.assertEqual({e["category"] for e in view.rows}, {"marine"})
        self.assertEqual(win.prefs["localCategory"], "marine")
        # Marine Ch 16: FM, the 25 kHz step.
        r = next(i for i, e in enumerate(view.rows) if e["name"] == "Marine Ch 16")
        self.assertEqual(self.cells(view, r)[2:4], ["156.800", "FM"])
        view.table.cellClicked.emit(r, 0)
        self.settle_until(lambda: radio.state()["vfo"] == 156_800_000.0)
        st = radio.state()
        self.assertEqual((st["vfo"], st["mode"]), (156_800_000.0, "fm"))
        self.assertEqual(win.step, 25000)
        self.assertFalse(st["keyed"])

    def test_an_833_channel_is_tuned_to_the_hertz(self):
        win, bridge, radio = self.window()
        win.show_view("local")
        view = win.local_view
        view.cat.setCurrentIndex(view.cat.findData("airband"))
        r = next(i for i, e in enumerate(view.rows) if e.get("step") == 8333)
        hz = view.rows[r]["freqHz"]
        view.table.cellClicked.emit(r, 1)
        self.settle_until(lambda: radio.state()["vfo"] == float(hz))
        self.assertEqual((radio.state()["vfo"], radio.state()["mode"]), (float(hz), "am"))
        # No 8.33 kHz step in the list: AM's own stays.
        self.assertNotEqual(win.step, 8333)
        self.assertIn(win.step, win.STEPS)

    def test_my_frequencies_from_settings(self):
        from PyQt6.QtWidgets import QDialog
        from ohsradio.ui import localview
        win, bridge, radio = self.window()
        d = win.settings_dialog()
        page = [i for i, p in enumerate(d.PAGES) if p[2] == "page_local"][0]
        d.nav.select(page)
        self.assertEqual(d.mine_table.rowCount(), 0)
        self.assertIn("ODbL", d.sources_label.text())

        answers = iter([{"name": "GB3GA", "mhz": "145.7125", "mode": "fm", "category": "repeater",
                         "locator": "io75tu"},
                        {"name": "GB3GA", "mhz": "145,7125", "mode": "fm", "category": "repeater", "locator": "",
                         "notes": "CTCSS 103.5"},
                        {"name": "GB3GA", "mhz": "145,7125", "mode": "fm", "category": "repeater", "locator": "",
                         "notes": "CTCSS 103.5"}])

        def run(dlg):
            a = next(answers)
            dlg.name.setText(a["name"])
            dlg.mhz.setText(a["mhz"])
            dlg.mode.setCurrentIndex(dlg.mode.findData(a["mode"]))
            dlg.category.setText(a["category"])
            dlg.locator.setText(a["locator"])
            dlg.notes.setText(a.get("notes", ""))
            dlg.accept()
            return dlg.result() == QDialog.DialogCode.Accepted
        orig = localview.MineDialog.exec
        localview.MineDialog.exec = run
        try:
            add, edit, delete = (d.mine_buttons[k] for k in ("add", "edit", "delete"))
            add.clicked.emit()
            self.assertEqual(d.mine_table.rowCount(), 1)
            e = radio.localfreq.mine.entries()[0]
            self.assertEqual((e["freqHz"], e["locator"]), (145_712_500, "IO75TU"))
            d.mine_table.selectRow(0)
            edit.clicked.emit()
            e = radio.localfreq.mine.entries()[0]
            self.assertEqual((e["locator"], e["notes"]), ("", "CTCSS 103.5"))
            d.mine_table.selectRow(0)
            delete.clicked.emit()
            self.assertEqual((d.mine_table.rowCount(), radio.localfreq.mine.entries()), (0, []))
            add.clicked.emit()               # back, for the view below
        finally:
            localview.MineDialog.exec = orig
        d.reject()
        win.show_view("local")
        win.local_view.refresh()
        mine = [x for x in win.local_view.rows if x["category"] == "mine"]
        self.assertEqual([x["name"] for x in mine], ["GB3GA"])

    def test_the_dialog_refuses_what_the_api_would(self):
        from ohsradio.ui.localview import MineDialog
        d = MineDialog(["fm", "am"])
        d.name.setText("X")
        d.mhz.setText("not a number")
        d.accept()
        self.assertTrue(d.error.isVisible() or d.error.text())
        self.assertIn("MHz", d.error.text())
        d.mhz.setText("145.5")
        d.locator.setText("ZZ99")
        d.accept()
        self.assertIn("locator", d.error.text())
        d.close()


if __name__ == "__main__":
    unittest.main()
