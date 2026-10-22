"""Settings › Converters in OpenHamShack NB (ohscore/ui/converters.py on the
shared dialog): add, edit, copy, delete, reorder and the preset packs,
what is saved, and the LNB and transmit choices that follow a rename. On
Qt's offscreen platform, against the simulator; behaviour only."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from ohscore import converters as cv
from ohsnb import converters as nbconv

from test_ui_window import WindowCase


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class NbConverters(WindowCase):
    def dialog(self, **over):
        from ohsnb.ui.settings import SettingsDialog
        win, bridge, radio = self.window(**over)
        titles = [t for _i, t, _b in SettingsDialog.PAGES]
        d = SettingsDialog(bridge, win.prefs, win, page=titles.index("Converters"))
        self.addCleanup(d.close)
        return d, radio

    def fill(self, ed, title, rx, typ="down", use="rx", tx="", inverted=False, drive=""):
        ed.f_title.setText(title)
        ed.f_type.set_value(typ, animate=False)
        ed.f_use.set_value(use, animate=False)
        ed.f_use.picked.emit(use)                     # as a click does
        ed.f_rx.setText(rx)
        ed.f_tx.setText(tx)
        ed.f_inv.set_on(inverted, emit=True)
        ed.f_drive.setText(drive)

    def rows(self, ed):
        return [[ed.table.item(r, c).text() for c in range(5)] for r in range(ed.table.rowCount())]

    def test_the_list_shows_the_lnb_in_sdr_console_s_columns(self):
        d, _ = self.dialog()
        self.assertEqual(self.rows(d.conv_editor), [["QO-100: LNB 9750 MHz", "Down", "RX only", "9,750,000,000", ""]])
        self.assertEqual(d.conv_combos["rxConverter"].currentData(), "QO-100: LNB 9750 MHz")

    def test_add_edit_reorder_delete_and_save(self):
        d, radio = self.dialog()
        ed = d.conv_editor
        ed.add()
        self.fill(ed, "1296 MHz (144 MHz IF)", "1152", use="rxtx")
        self.assertTrue(ed.form_ok())
        self.assertEqual(self.rows(ed)[-1], ["1296 MHz (144 MHz IF)", "Down", "RX/TX", "1,152,000,000",
                                             "1,152,000,000"])
        # The example is on the uplink for a transmitting converter that cannot take the downlink.
        ed.table.selectRow(1)
        ed.edit()
        self.assertEqual(ed.f_rx.text(), "1152")
        self.assertIn("2400-2400.5 MHz on air is sent from 1248-1248.5 MHz on the radio", ed.example.text())
        self.fill(ed, "Up 1152", "1152", use="rxtx", inverted=True)
        self.assertIn("inverted", ed.example.text())
        self.fill(ed, "Up 1152", "1152", use="rxtx")
        self.assertTrue(ed.form_ok())
        ed.add_pack("qo100")
        n = len(ed.titles())
        ed.add_pack("qo100")                                  # a second press adds nothing
        self.assertEqual(len(ed.titles()), n)
        ed.table.selectRow(1)
        ed.move(-1)
        self.assertEqual(ed.titles()[:2], ["Up 1152", "QO-100: LNB 9750 MHz"])
        ed.table.selectRow(0)
        ed.copy()
        self.assertEqual(ed.titles()[1], "Up 1152 (2)")
        ed.table.selectRow(1)
        ed.delete()
        self.assertNotIn("Up 1152 (2)", ed.titles())
        d.save()
        self.assertEqual(d.error.text(), "")
        saved = radio.state()["converters"]
        self.assertEqual([c["title"] for c in saved], ed.titles())
        self.assertEqual(cv.find(saved, "Up 1152").tx_offset, 1_152_000_000.0)

    def test_the_lnb_in_use_cannot_be_deleted_and_a_rename_is_followed(self):
        d, radio = self.dialog()
        ed = d.conv_editor
        ed.table.selectRow(0)
        ed.delete()
        self.assertIn("in use", ed.note.text())
        self.assertEqual(len(ed.titles()), 1)
        ed.edit()
        ed.f_title.setText("My Bullseye")
        self.assertTrue(ed.form_ok())
        self.assertEqual(d.conv_combos["rxConverter"].currentData(), "My Bullseye")
        d.save()
        self.assertEqual(radio.state()["rxConverter"], "My Bullseye")
        self.assertEqual(nbconv.rx_lo(radio.state()), 9_750_000_000.0)

    def test_choosing_another_lnb_and_the_pluto_s_upconverter(self):
        d, radio = self.dialog()
        d.conv_editor.add_pack("qo100")
        rx, tx = d.conv_combos["rxConverter"], d.conv_combos["txConverter"]
        # Only what can be the LNB is offered as the LNB, only RX/TX ones to transmit through.
        self.assertNotIn("QO-100 uplink: 1296 MHz IF (LO 1104)", [rx.itemData(i) for i in range(rx.count())])
        self.assertNotIn("QO-100: LNB 9750.1 MHz", [tx.itemData(i) for i in range(tx.count())])
        rx.setCurrentIndex(rx.findData("QO-100: LNB 9750.1 MHz"))
        tx.setCurrentIndex(tx.findData("QO-100 uplink: 432 MHz IF (LO 1968)"))
        d.save()
        st = radio.state()
        self.assertEqual((st["rxConverter"], st["txConverter"]),
                         ("QO-100: LNB 9750.1 MHz", "QO-100 uplink: 432 MHz IF (LO 1968)"))

    def test_a_tx_only_upconverter_is_an_up_converter_offered_only_to_transmit(self):
        # Ray's station: the IC-9700 through an upconverter from 1296 MHz,
        # an SDR receiving. TX only greys the RX offset, wants the TX one
        # and names the type by what it does on transmit.
        d, radio = self.dialog()
        ed = d.conv_editor
        ed.add()
        self.fill(ed, "Ray's upconverter", "", use="tx")
        self.assertFalse(ed.f_rx.isEnabled())
        self.assertTrue(ed.f_tx.isEnabled() and ed.f_drive.isEnabled())
        self.assertEqual(dict(ed.f_type.options)["down"], "Up-converter")
        self.assertFalse(ed.form_ok())
        self.assertIn("TX offset", ed.f_error.text())
        ed.f_tx.setText("1104")
        self.assertIn("2400-2400.5 MHz on air is sent from 1296-1296.5 MHz on the radio", ed.example.text())
        self.assertTrue(ed.form_ok())
        self.assertEqual(self.rows(ed)[-1], ["Ray's upconverter", "Up", "TX only", "", "1,104,000,000"])
        # Back to RX/TX, the same type is the transverter's Down-converter again.
        ed.table.selectRow(1)
        ed.edit()
        self.assertEqual((ed.f_use.value, ed.f_tx.text()), ("tx", "1104"))
        ed.f_use.set_value("rxtx", animate=False)
        ed.f_use.picked.emit("rxtx")
        self.assertEqual(dict(ed.f_type.options)["down"], "Down-converter")
        ed.form_cancel()
        rx, tx, rig = (d.conv_combos[k] for k in ("rxConverter", "txConverter", "rigTxConverter"))
        self.assertNotIn("Ray's upconverter", [rx.itemData(i) for i in range(rx.count())])
        for cb in (tx, rig):
            self.assertIn("Ray's upconverter", [cb.itemData(i) for i in range(cb.count())])
        rig.setCurrentIndex(rig.findData("Ray's upconverter"))
        d.save()
        self.assertEqual(d.error.text(), "")
        self.assertEqual(nbconv.rig_converter(radio.state()).use, cv.TX)

    def test_bad_form_input_is_refused_with_a_sentence_and_nothing_changes(self):
        d, _ = self.dialog()
        ed = d.conv_editor
        ed.add()
        self.fill(ed, "QO-100: LNB 9750 MHz", "9750")
        self.assertFalse(ed.form_ok())
        self.assertIn("already a converter called", ed.f_error.text())
        self.fill(ed, "x", "nine")
        self.assertFalse(ed.form_ok())
        self.assertIn("RX offset", ed.f_error.text())
        self.fill(ed, "x", "116", use="rxtx", drive="lots")
        self.assertFalse(ed.form_ok())
        self.assertIn("dBm", ed.f_error.text())
        self.assertEqual(len(ed.titles()), 1)

    def test_saved_converters_are_written_to_the_config_file_and_read_back(self):
        import tempfile
        from pathlib import Path
        from ohsnb import config
        d, radio = self.dialog()
        ed = d.conv_editor
        ed.add()
        self.fill(ed, "Mine", "9750.0123")
        self.assertTrue(ed.form_ok())
        d.save()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            config.save(radio.cfg, p)
            back = config.load(p)
        self.assertEqual(cv.find(back["converters"], "Mine").rx_offset, 9_750_012_300.0)
        self.assertEqual([c["title"] for c in back["converters"]], ed.titles())


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class HamConverters(unittest.TestCase):
    """The same page in OpenHamShack HAM: a converter per band, the most drive
    required of a transmitting one, and the band bar offering a band the
    radio reaches only through one."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        self.wins = []

    def tearDown(self):
        for win, bridge in self.wins:
            win.close()
            bridge.stop()
        self.app.processEvents()

    def window(self, **over):
        from ham_helpers import make_radio
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        radio = make_radio(simSignals=False, **over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.app.processEvents()
        return win, bridge, radio

    def dialog(self, win, bridge):
        from ohsradio.ui.settings import SettingsDialog
        titles = [t for _i, t, _b in SettingsDialog.PAGES]
        d = SettingsDialog(bridge, win.prefs, win, page=titles.index("Converters"))
        self.addCleanup(d.close)
        return d

    def test_a_band_through_a_transverter_needs_its_most_drive_and_then_saves(self):
        win, bridge, radio = self.window()
        d = self.dialog(win, bridge)
        ed = d.conv_editor
        self.assertEqual(ed.titles(), [])
        ed.add_pack("vhf")
        self.assertIn("1296 MHz (144 MHz IF)", ed.titles())
        cb = d.band_conv["23cm"]
        cb.setCurrentIndex(cb.findData("1296 MHz (144 MHz IF)"))
        d.save()
        self.assertIn("most drive", d.error.text())                 # the presets carry none, on purpose
        self.assertEqual(radio.state()["bandConverters"], {})
        ed.table.selectRow(ed.titles().index("1296 MHz (144 MHz IF)"))
        ed.edit()
        self.assertIn("1240-1325 MHz on air appears at 88-173 MHz on the radio", ed.example.text())
        self.assertIn("required", ed.drive_cap.text())
        self.assertFalse(ed.form_ok())                              # HAM will not take an RX/TX one without it
        ed.f_drive.setText("0")
        self.assertTrue(ed.form_ok())
        # In use now: it cannot be deleted from under the band.
        ed.delete()
        self.assertIn("23cm is worked through it", ed.note.text())
        d.save()
        st = radio.state()
        self.assertEqual(st["bandConverters"], {"23cm": "1296 MHz (144 MHz IF)"})
        self.assertEqual(cv.find(st["converters"], "1296 MHz (144 MHz IF)").max_drive_dbm, 0.0)

    def test_a_tx_only_converter_needs_its_most_drive_and_the_band_bar_says_it_receives_directly(self):
        win, bridge, radio = self.window()
        d = self.dialog(win, bridge)
        ed = d.conv_editor
        ed.add()
        ed.f_title.setText("2 m upconverter")
        ed.f_use.set_value("tx", animate=False)
        ed.f_use.picked.emit("tx")
        ed.f_tx.setText("116")
        self.assertIn("required", ed.drive_cap.text())
        self.assertIn("144-146 MHz on air is sent from 28-30 MHz on the radio", ed.example.text())
        self.assertFalse(ed.form_ok())
        self.assertIn("Most drive", ed.f_error.text())
        ed.f_drive.setText("0")
        self.assertTrue(ed.form_ok())
        cb = d.band_conv["2m"]
        cb.setCurrentIndex(cb.findData("2 m upconverter"))
        d.save()
        self.assertEqual(d.error.text(), "")
        self.assertEqual(radio.state()["bandConverters"], {"2m": "2 m upconverter"})
        from ohsradio import bands
        status, why = win.bandbar._status(bands.BY_NAME["2m"])
        self.assertEqual(status, "tx")
        self.assertIn("through 2 m upconverter (transmit only: received directly)", why)

    def test_the_band_bar_offers_6m_through_a_converter(self):
        six = {"title": "6m xvtr", "type": "down", "rxtx": True, "rxOffset": 22e6, "txOffset": 22e6,
               "maxDriveDbm": 0.0}
        win, bridge, radio = self.window()
        from ohsradio import bands
        self.assertEqual(win.bandbar._status(bands.BY_NAME["6m"])[0], "off")
        win2, bridge2, radio2 = self.window(converters=[six], bandConverters={"6m": "6m xvtr"})
        status, why = win2.bandbar._status(bands.BY_NAME["6m"])
        self.assertEqual(status, "tx")
        self.assertIn("through 6m xvtr", why)
        win2.pick_band("6m")
        self.assertEqual(radio2.state()["band"], "6m")
        radio2.set(vfo=50_200_000.0)
        self.assertEqual(win2.readout.bridge.face.secondary(radio2.state()), ("IF", "28.200 000  6m xvtr"))


if __name__ == "__main__":
    unittest.main()
