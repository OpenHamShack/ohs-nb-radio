"""The band activity and the QSO card after the UI overhaul's WP4
(docs/ui-overhaul-2026-10.md sections 5.3, 5.7, 5.9, 5.10 and section 3's
Tight rule): times as 15:38:45, short country names, messages to us in
gold, our own overs in our own gold, Halt TX and the chosen Tx row red only
while armed or on the air, the pile-up line, the narrow list, and JS8's
speed kept across a restart.

They drive the window on the simulator and read what it shows or paints.
Where the simulator is keyed it is the simulator's own transmitter, which
radiates nothing (Device.radiates)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor
    from PyQt6.QtTest import QTest
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from ohscore import dxcc
from test_ui_colours import red_pixels, themes
from test_ui_window import WindowCase

FT8_DL = 10_489_540_000.0
# 15:38:45 UTC on 17/10/2026: an odd FT8 slot (15:38:30 + 15 s).
SLOT_153845 = 1_792_251_525.0


class ShortNames(unittest.TestCase):
    def test_every_long_name_in_the_bundled_file_has_a_short_form(self):
        c = dxcc.Countries(dxcc.BUNDLED.read_text(encoding="latin-1"))
        names = {e.name for e in list(c.prefixes.values()) + list(c.exact.values())}
        long = sorted(n for n in names if len(n) > 14)
        self.assertGreater(len(long), 50)
        missing = [n for n in long if n not in dxcc.short_names()]
        self.assertEqual(missing, [])
        for n in long:
            ent = dxcc.Entity(n, "EU", "X")
            self.assertLessEqual(len(ent.short), 14, n)

    def test_short_and_full(self):
        c = dxcc.load()
        de = c.lookup("DL1ABC")
        self.assertEqual((de.name, de.short), ("Fed. Rep. of Germany", "Germany"))
        self.assertEqual(c.lookup("UA3ABC").short, "Russia")
        # A name with no entry is itself.
        self.assertEqual(c.lookup("G4ABC").short, c.lookup("G4ABC").name)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class DecodeList(WindowCase):
    def ft8(self, **over):
        from ohscore.ui.panels.ft8 import Ft8Panel
        over.setdefault("mode", "ft8")
        over.setdefault("vfo", FT8_DL)
        win, bridge, radio = self.window(callsign="GM4BRI", locator="IO75RL", **over)
        self.assertTrue(self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=10))
        self.app.processEvents()
        return win, bridge, radio, win.panel

    def decode(self, p, text, call="", snr=-6, df=1514, slot=SLOT_153845):
        ev = {"mode": "ft8", "slot": slot, "text": text, "snr": snr, "dt": 0.3, "df": df}
        if call:
            ev["call"] = call
        p.on_event(ev)
        return p.table.rowCount() - 1

    def test_times_read_with_colons(self):
        win, bridge, radio, p = self.ft8()
        r = self.decode(p, "CQ DL1ABC JO31", "DL1ABC")
        self.assertEqual(p.table.item(r, 0).text(), "15:38:45")
        self.assertEqual(p.table.item(r - 1, 0).text(), "15:38:45")      # the slot's separator

    def test_country_is_short_with_the_full_name_in_the_tooltip(self):
        win, bridge, radio, p = self.ft8()
        r = self.decode(p, "CQ DL1ABC JO31", "DL1ABC")
        cell = p.table.item(r, 6)
        self.assertEqual(cell.text(), "Germany")
        self.assertIn("Fed. Rep. of Germany", cell.toolTip())
        # The column holds the longest short name whole.
        fm = p.table.fontMetrics()
        self.assertGreaterEqual(p.table.columnWidth(6), fm.horizontalAdvance("Turks & Caicos"))

    def test_the_list_text_is_16_px_by_default(self):
        win, bridge, radio, p = self.ft8()
        self.assertEqual(p.prefs["ft8FontPx"], 16.0)

    def test_a_message_to_us_is_gold_and_our_over_is_our_own_gold(self):
        from ohscore.ui import theme
        win, bridge, radio, p = self.ft8()
        r = self.decode(p, "GM4BRI DL1ABC -05", "DL1ABC")
        bg = p.table.item(r, 5).background().color()
        self.assertEqual(bg.rgb(), theme.c("toYou").rgb())
        # Our own over, as the sequencer logs it, in `own`, not red.
        p.seq.answer("DL1ABC", "JO31", -5)
        p.set_tx_enabled(True)
        p.fresh = "operator"
        with mock.patch.object(p.bridge, "send", return_value=True):
            for t in (SLOT_153845 + 15.5, SLOT_153845 + 30.2):
                with mock.patch("ohscore.ui.panels.ft8.time.time", return_value=t):
                    p.tick(0.03)
        p.set_tx_enabled(False)
        last = p.table.rowCount() - 1
        self.assertTrue(p.table.item(last, 5).text().startswith("TX  DL1ABC GM4BRI"))
        self.assertEqual(p.table.item(last, 5).foreground().color().rgb(), theme.c("own").rgb())
        self.assertEqual(p.table.item(last, 0).text().count(":"), 2)
        # The legend's "to you" swatch is the same gold.
        self.assertIn(theme.t()["toYou"], p.legend.text())

    def test_narrow_list_hides_dt_and_freq_and_the_tooltip_has_them(self):
        win, bridge, radio, p = self.ft8()
        r = self.decode(p, "CQ DL1ABC JO31", "DL1ABC")
        win.resize(1920, 1080)
        self.assertTrue(self.run_for(radio, until=lambda: p.act_card.width() > 700, timeout=5))
        self.app.processEvents()
        self.assertFalse(p.table.isColumnHidden(2) or p.table.isColumnHidden(3))
        # About 640 px at the default 16 px, as the plan put it.
        self.assertTrue(600 <= p.narrow_below() <= 680, p.narrow_below())
        # 1366 x 768: beside the QSO card the list is under 500 px.
        win.resize(1366, 768)
        self.assertTrue(self.run_for(radio, until=lambda: p.act_card.width() < 600, timeout=5),
                        p.act_card.width())
        self.app.processEvents()
        self.assertTrue(p.table.isColumnHidden(2) and p.table.isColumnHidden(3) and p.table.isColumnHidden(4))
        tip = p.table.item(r, 5).toolTip()
        self.assertIn("+0.3", tip)
        self.assertIn("1514", tip)
        # The message keeps what DT and Freq gave up.
        self.assertGreaterEqual(p.table.columnWidth(5), p.table.fontMetrics().horizontalAdvance("0" * 14))
        # At the window's smallest with the rail showing (300 px of list) the
        # country goes too, named in the tooltip, before the message shrinks.
        # (Since WP6 the rail is in the Tight tier's drawer at this size, so
        # the list is wider; the country still goes.)
        win.resize(1024, 600)
        self.assertTrue(self.run_for(radio, until=lambda: p.act_card.width() < 600, timeout=5))
        self.assertTrue(self.run_for(radio, until=lambda: p.table.isColumnHidden(6), timeout=5))
        self.assertIn("Fed. Rep. of Germany", p.table.item(r, 5).toolTip())
        self.assertGreaterEqual(p.table.columnWidth(5), p.table.fontMetrics().horizontalAdvance("0" * 9))
        win.resize(1920, 1080)
        self.assertTrue(self.run_for(radio, until=lambda: not p.table.isColumnHidden(2), timeout=5))
        self.assertFalse(p.table.isColumnHidden(6))

    def test_the_panel_fits_a_1024_x_600_window(self):
        # WP1 found the slot panel wanted ~890 x 430, more than Digital
        # gives it at 1366 wide. With the narrow list and the Tx rows
        # scrolling it fits the lower panel the Tight tier leaves at
        # 1024 x 600 (the window less a 160 px zoom), header buttons whole.
        win, bridge, radio, p = self.ft8()
        hint = p.minimumSizeHint()
        self.assertLessEqual(hint.width(), 1024 - 160 - 100, hint)
        self.assertLessEqual(hint.height(), 300, hint)
        win.resize(1024, 600)
        self.run_for(radio, 0.3)
        hdr = p.qso_card.header_right
        self.assertGreaterEqual(hdr.width(), hdr.sizeHint().width())
        # The DX call and Enable TX stay in view; the Tx rows scroll.
        for w in (p.dx, p.enable, p.halt):
            self.assertTrue(w.isVisible())
            self.assertTrue(p.qso_card.rect().contains(w.mapTo(p.qso_card, w.rect().bottomRight())), w)

    # ------------------------------------------------------------ pile-up
    def pile(self, p, slot=None):
        slot = slot or time.time() // 15 * 15 - 15
        for text, call, snr in (("7P8GE RD7P LN23", "RD7P", -6), ("7P8GE R5DT KO94", "R5DT", -4),
                                ("7P8GE EA7KP IM97", "EA7KP", 1), ("7P8GE LZ1GHT KN12", "LZ1GHT", -9),
                                ("7P8GE DD8KO JO30", "DD8KO", -4)):
            self.decode(p, text, call, snr, slot=slot)

    def test_the_pile_up_line_and_a_click_on_it(self):
        win, bridge, radio, p = self.ft8()
        self.assertFalse(p.pile_line.isVisible())
        self.pile(p)
        self.app.processEvents()
        self.assertTrue(p.pile_line.isVisible())
        line = p.pile_line.toolTip()
        self.assertTrue(line.startswith("Pile-up: 7P8GE (Lesotho) · 5 calling: EA7KP +1, DD8KO -4, R5DT -4, +2 more"),
                        line)
        self.assertTrue(line.endswith("you: not calling"), line)
        # A click puts the station in the DX call and sends nothing.
        with mock.patch.object(p.bridge, "send") as send:
            QTest.mouseClick(p.pile_line, Qt.MouseButton.LeftButton)
            self.assertEqual(p.dx.text(), "7P8GE")
            self.assertFalse(p.tx_enabled)
            send.assert_not_called()
        # While Enable TX is on, a click does not turn the QSO elsewhere.
        p.seq.answer("DL1ABC", "JO31")
        p.set_tx_enabled(True)
        QTest.mouseClick(p.pile_line, Qt.MouseButton.LeftButton)
        self.assertEqual(p.seq.dx, "DL1ABC")
        p.set_tx_enabled(False)

    def test_the_pile_up_line_ages_out_and_is_ft8s_alone(self):
        win, bridge, radio, p = self.ft8()
        self.pile(p, slot=time.time() // 15 * 15 - 120)
        p.pile_slot = None
        p.tick(0.03)
        self.assertFalse(p.pile_line.isVisible())

    # ------------------------------------------------------------ Halt TX
    def test_halt_is_neutral_idle_red_armed_and_keyed_and_always_halts(self):
        win, bridge, radio, p = self.ft8()
        p.tick(0.03)
        self.app.processEvents()
        self.assertTrue(p.halt.isVisible())
        for name in themes():
            p.halt.update()
            self.assertEqual(red_pixels(p.halt), 0, name)
        # The chosen Tx row: accent, not red, while idle.
        cur = next(r for r in p.rows if r.current)
        self.assertEqual(red_pixels(cur), 0)
        # Armed.
        p.seq.answer("DL1ABC", "JO31")
        with mock.patch.object(p.bridge, "send", return_value=True):
            p.set_tx_enabled(True)
            p.tick(0.03)
            for _ in range(30):
                self.app.processEvents()
                time.sleep(0.01)
            self.assertGreater(red_pixels(p.halt), 100)
            cur = next(r for r in p.rows if r.current)
            self.assertGreater(red_pixels(cur), 20)
            with mock.patch.object(p.bridge, "halt") as halt:
                p.halt.clicked.emit()
            self.assertFalse(p.tx_enabled)
        p.tick(0.03)
        self.app.processEvents()
        self.assertEqual(p.halt.kind, "plain")
        # Keyed (the simulator, by PTT): red, and a click halts the air.
        bridge.ptt(True)
        try:
            self.assertTrue(self.run_for(radio, until=lambda: bridge.face.on_air(bridge.st), timeout=10))
            p.tick(0.03)
            self.assertEqual(p.halt.kind, "danger")
            p.halt.clicked.emit()
            self.assertTrue(self.run_for(radio, until=lambda: not bridge.st.get("keyed"), timeout=10))
        finally:
            bridge.ptt(False)
        p.tick(0.03)
        self.assertEqual(p.halt.kind, "plain")

    def test_halt_hides_when_this_run_cannot_transmit(self):
        from ohscore.config import receive_only
        over = {}
        receive_only(over)
        win, bridge, radio, p = self.ft8(**over)
        self.run_for(radio, 0.3)
        p.tick(0.03)
        self.app.processEvents()
        self.assertFalse(p.halt.isVisible())
        # Hidden, it still halts if reached (Escape's path is the window's).
        with mock.patch.object(p.bridge, "halt"):
            p.halt_tx()
        self.assertFalse(p.tx_enabled)

    # ------------------------------------------------------------ JS8
    def test_js8_halt_is_neutral_and_its_speed_survives_a_restart(self):
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        win, bridge, radio, p = self.ft8(mode="js8", vfo=10_489_548_000.0)
        js = p.js8
        self.assertIsNotNone(js)
        p.tick(0.03)
        self.app.processEvents()
        self.assertEqual(js.halt.kind, "plain")
        self.assertEqual(red_pixels(js.halt), 0)
        js.set_speed("fast")
        self.assertEqual(Prefs(config.CONFIG)["js8Speed"], "fast")
        win2, bridge2, radio2, p2 = self.ft8(mode="js8", vfo=10_489_548_000.0)
        self.assertEqual(p2.js8.speed, "fast")
        self.assertEqual(p2.js8.speed_pick.value, "fast")


if __name__ == "__main__":
    unittest.main()
