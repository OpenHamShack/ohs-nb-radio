"""What was still cut off after the window tiers (UI overhaul phase 2's
report, docs/ui-overhaul-2026-10.md): the FT8 panel's QSO card, the voice
panel's sliders at 130 % text, and NB's own-signal-vs-beacon meter on a
narrow rail. Measured on the real window on the simulator at the sizes
and text scales test_ui_tiers.py uses, as geometry: what each widget was
given against what its text needs, and where it sits against what holds
it. Nothing here keys anything."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_ui_tiers import HAVE_QT, SIZES, WindowCase, squeezed


def inside(w, holder, slack=0.5) -> bool:
    """Whether `w` is drawn wholly within `holder`'s rect."""
    from PyQt6.QtCore import QPoint
    tl = w.mapTo(holder, QPoint(0, 0))
    r = holder.rect()
    return (tl.x() >= r.left() - slack and tl.y() >= r.top() - slack
            and tl.x() + w.width() <= r.right() + 1 + slack and tl.y() + w.height() <= r.bottom() + 1 + slack)


def ft8_panel(win):
    from ohscore.ui.panels.ft8 import Ft8Panel
    return next(p for p in win.findChildren(Ft8Panel) if p.isVisible())


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class QsoCard(WindowCase):
    """The card keeps its header (Halt TX), the DX fields and Enable TX in
    view at every size, and the Tx rows give way first, scrolling."""

    def check_card(self, win, label):
        p = ft8_panel(win)
        q = p.qso_card
        self.assertEqual([s for s in squeezed(win) if "QLineEdit" in s or "Card" in s], [], label)
        for w in (p.halt, p.log_btn, p.dx, p.dxgrid, p.ring, p.period, p.enable, p.auto, p.lock, p.hold,
                  p.rows_area):
            self.assertTrue(w.isVisible(), (label, type(w).__name__))
            self.assertTrue(inside(w, q), (label, type(w).__name__))
        for w in (p.dx, p.dxgrid):
            self.assertGreaterEqual(w.height(), w.minimumSizeHint().height(), label)
        # The row going next is whole in the rows' viewport.
        view = p.rows_area.viewport()
        self.assertTrue(inside(p.rows[p.seq.next - 1], view), (label, p.seq.next))
        return p

    def test_every_size_and_text_scale(self):
        for size, scale, _tier in SIZES:
            win, bridge, radio = self.window(size=size, scale=scale, mode="ft8")
            label = f"{self.APP} {size[0]}x{size[1]} at {scale}"
            p = self.check_card(win, label)
            if size == (1920, 1080):
                # Room for all six: the rows take it before any blank below
                # the toggles (Tx6 was cut off above one at 130 %).
                self.assertEqual(p.rows_area.height(), p.rows_area.maximumHeight(), label)
                self.assertFalse(p.qso_short, label)
            win.close()
            bridge.stop()
            self.wins.remove((win, bridge))


    def test_words_in_the_ring_and_rows_make_room_for_a_longer_language(self):
        from unittest import mock
        from PyQt6.QtGui import QFontMetricsF
        from ohscore.ui.panels.ft8 import SlotRing, TxRow
        from ohscore.ui import theme
        win, bridge, radio = self.window(size=(1920, 1080), scale=1.3, mode="ft8")
        p = ft8_panel(win)
        row = p.rows[5]
        english = row.tag()[2]
        with mock.patch.object(TxRow, "tr", lambda _self, t: "[Ťx{n}~~~~]"):
            _tag, font, x = row.tag()
        self.assertGreaterEqual(x, 8 + QFontMetricsF(font).horizontalAdvance("[Ťx6~~~~]") + 8)
        self.assertGreater(x, english)
        word = "[ÉVÉÑ~~]"
        room = QFontMetricsF(theme.caps(10)).horizontalAdvance(word) * 0.8
        f = SlotRing.fitted(theme.caps(10), word, room)
        self.assertLessEqual(QFontMetricsF(f).horizontalAdvance(word), room)
        self.assertLess(f.pixelSize(), theme.caps(10).pixelSize())
        # The grid field holds a six-character locator at this text size.
        fm = QFontMetricsF(p.dxgrid.font())
        self.assertGreaterEqual(p.dxgrid.width(), fm.horizontalAdvance("IO75RL") + 12)


class RadioQsoCard(QsoCard):
    APP = "radio"

    def test_a_short_card_takes_its_short_form_and_back(self):
        # Radio at 1024 wide: the band buttons and the "ohsdigi did not
        # load" line (on a host without it) leave the card under its full
        # height at 600, where the DX fields were squeezed to 16 px.
        win, bridge, radio = self.window(size=(1024, 600), mode="ft8")
        p = ft8_panel(win)
        forms = set()
        squeezed = False
        for h in range(600, 781, 12):
            win.resize(1024, h)
            self.settle(3)
            forms.add(p.qso_short)
            # Below what the full form needs, the card must be short.
            if p.qso_card.height() < p.qso_full_need:
                squeezed = True
                self.assertTrue(p.qso_short, h)
            self.check_card(win, f"1024x{h}")
            # In either form the card is never given less than it asks.
            self.assertGreaterEqual(p.qso_card.height(), p.qso_card.minimumSizeHint().height() - 1, h)
            self.assertEqual(p.offsets.isVisible(), not p.qso_short, h)
        win.resize(1024, 780)
        self.settle(3)
        self.assertFalse(p.qso_short)
        self.assertEqual(p.ring.width(), p.ring.FULL)
        # Both forms only where 600 really squeezed the card: with ohsdigi
        # loaded (no "did not load" line) and some hosts' fonts, the full
        # form fits at 1024 x 600 and the short one is rightly never taken.
        if squeezed and p.qso_card.height() > p.qso_full_need:
            self.assertEqual(forms, {True, False})

    def test_the_short_form_scrolls_to_the_row_going_next(self):
        win, bridge, radio = self.window(size=(1024, 600), mode="ft8")
        p = ft8_panel(win)
        if not p.qso_short:
            self.skipTest("the card has its full height here (the decoder loaded, so no line above it)")
        view = p.rows_area.viewport()
        for n in (6, 1, 4):
            p.choose(n)
            self.settle(2)
            self.assertTrue(inside(p.rows[n - 1], view), n)
        # The operator's own scrolling is not undone by the next refresh.
        bar = p.rows_area.verticalScrollBar()
        bar.setValue(bar.maximum())
        p._refresh()
        self.assertEqual(bar.value(), bar.maximum())


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class VoiceSliders(WindowCase):
    def test_labels_and_values_whole_at_every_size(self):
        # At 130 % "Low edge" ran into "300 Hz" and "Monitor level" read
        # "Monitor leve": each slider is now at least as wide as its label,
        # a gap and its widest value.
        from PyQt6.QtGui import QFontMetricsF
        from ohscore.ui.controls import Slider
        from ohscore.ui.panels.voice import VoicePanel
        for size, scale, _tier in SIZES:
            win, bridge, radio = self.window(size=size, scale=scale, mode="usb")
            win.close_drawer()
            self.settle(2)
            label = f"{self.APP} usb {size[0]}x{size[1]} at {scale}"
            panel = next(p for p in win.findChildren(VoicePanel) if p.isVisible())
            sliders = [s for s in panel.findChildren(Slider) if s.isVisible()]
            self.assertGreaterEqual(len(sliders), 4, label)
            for s in sliders:
                need = (QFontMetricsF(s._label_font()).horizontalAdvance(s.label) + s.GAP
                        + QFontMetricsF(s._value_font()).horizontalAdvance(s.fmt(s.v)))
                self.assertGreaterEqual(s.width(), need, (label, s.label))
                self.assertTrue(inside(s, panel), (label, s.label))
            win.close()
            bridge.stop()
            self.wins.remove((win, bridge))

    def test_a_wider_range_asks_for_more_room(self):
        from ohscore.ui.controls import Slider
        s = Slider("Low edge", 0, 500, 300, 50, lambda v: f"{v:.0f} Hz")
        before = s.minimumSizeHint().width()
        s.set_range(0, 50000)
        self.assertGreater(s.minimumSizeHint().width(), before)


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class LeastWidths(WindowCase):
    def test_toggles_and_segmented_rows_ask_for_their_whole_labels(self):
        # Neither claimed a least width, so a short layout cut "Monitor" to
        # "M" and ran the AGC choices into each other with nothing noticing.
        from PyQt6.QtGui import QFontMetricsF
        from ohscore.ui import theme
        from ohscore.ui.controls import Segmented, Toggle
        t = Toggle("Monitor level and more")
        self.assertGreaterEqual(t.minimumSizeHint().width(),
                                QFontMetricsF(theme.font(12.5)).horizontalAdvance(t.label) + 34)
        self.assertLess(Toggle("Monitor", show_label=False).minimumSizeHint().width(), 50)
        seg = Segmented([("a", "Off"), ("b", "Medium-long label"), ("c", "Slow")], compact=True)
        fm = QFontMetricsF(theme.font(12, theme.QFont.Weight.DemiBold))
        self.assertGreaterEqual(seg.minimumSizeHint().width(), 3 * fm.horizontalAdvance("Medium-long label"))


class RadioVoiceSliders(VoiceSliders):
    APP = "radio"


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class BeaconMeterFits(WindowCase):
    def test_its_lines_fit_and_its_figures_stand_apart(self):
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QFontMetricsF
        from ohscore.ui import theme
        for size, scale, tier in SIZES:
            win, bridge, radio = self.window(size=size, scale=scale, mode="usb")
            if tier == "tight":
                win.open_drawer()
                self.settle(2)
            m = win.txcard.beacon
            label = f"{size[0]}x{size[1]} at {scale}, {m.width()} px"
            self.assertTrue(m.isVisible(), label)
            fonts = m._fonts()
            # Every line below the one before it, the last inside the meter.
            r = m.rows
            self.assertGreaterEqual(r["hint"], QFontMetricsF(fonts["value"]).height(), label)
            self.assertGreaterEqual(r["bar"], r["hint"] + QFontMetricsF(fonts["tag"]).height(), label)
            self.assertGreaterEqual(r["ticks"], r["bar"] + 14, label)
            self.assertGreaterEqual(r["foot"], r["ticks"] + QFontMetricsF(fonts["tick"]).height(), label)
            self.assertLessEqual(r["foot"] + QFontMetricsF(fonts["foot"]).height(), m.height(), label)
            tag = m.tag_box(QRectF(0, r["bar"], m.width(), 14))
            self.assertGreaterEqual(tag.left(), 0, label)
            self.assertLessEqual(tag.right(), m.width(), label)
            boxes = m.tick_labels(QRectF(0, r["bar"], m.width(), 14), fonts["tick"])
            self.assertIn("−6", [t for _b, t, _k in boxes], label)        # the margin always shows
            for i, (a, ta, _k) in enumerate(boxes):
                self.assertGreaterEqual(a.left(), 0, label)
                self.assertLessEqual(a.right(), m.width(), label)
                for b, tb, _k2 in boxes[i + 1:]:
                    self.assertFalse(a.adjusted(-2, 0, 2, 0).intersects(b), (label, ta, tb))
            theme.set_scale(1.0)
            win.close()
            bridge.stop()
            self.wins.remove((win, bridge))


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class TxBandRuler(WindowCase):
    def test_its_figures_stay_inside_and_apart(self):
        # "3k" lost its last pixels off the right edge (WP9, 1024 x 600).
        from PyQt6.QtGui import QFontMetricsF
        from ohscore.ui import theme
        from ohscore.ui.panels.voice import TxBand
        for scale in (1.0, 1.3):
            theme.set_scale(scale)
            for width in (260, 296, 420):
                band = TxBand()
                self.addCleanup(band.deleteLater)
                band.resize(width, band.height())
                fm = QFontMetricsF(band._tick_font())
                boxes = band.tick_labels()
                self.assertEqual([t for _b, t in boxes], ["0", "0.5k", "1k", "1.5k", "2k", "2.5k", "3k"])
                for i, (a, ta) in enumerate(boxes):
                    label = (scale, width, ta)
                    self.assertGreaterEqual(a.left(), 0, label)
                    self.assertLessEqual(a.right(), width, label)
                    self.assertGreaterEqual(a.width(), fm.horizontalAdvance(ta), label)
                    for b, _tb in boxes[i + 1:]:
                        self.assertFalse(a.intersects(b), (label, b))
                band.grab()                                      # and it paints what it laid out
        theme.set_scale(1.0)


if __name__ == "__main__":
    unittest.main()
