"""Beacon lock from the window: right-click a beacon on a scope, H for
Hold, and the RX badge's panel and wheel in Manual - driven as an operator
would, checked against what the engine was told."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from test_ui_window import HAVE_QT, WindowCase

if HAVE_QT:
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

from ohsnb import bandplan
from test_beacon_modes import DecoySim

MIDDLE = bandplan.BEACONS["middle"]["ref"]


def wheel(widget, up: bool, shift: bool = False):
    mods = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
    c = QPointF(widget.width() / 2, widget.height() / 2)
    ev = QWheelEvent(c, QPointF(widget.mapToGlobal(c.toPoint())), QPoint(0, 0), QPoint(0, 120 if up else -120),
                     Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class BeaconLockUi(WindowCase):
    def test_right_click_on_the_real_beacon_moves_the_lock_to_it(self):
        # LNB 45 kHz out, a louder BPSK copy that beacon lock prefers (see
        # test_beacon_modes.DecoySim). The operator right-clicks the real
        # beacon on the wide scope, a little off its centre.
        win, bridge, radio = self.window(device=DecoySim, simRxErrorHz=45_000.0)
        self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked", timeout=20)
        self.assertAlmostEqual(radio.state()["rxCorr"], 25_000.0, delta=5.0)
        self.run_for(radio, 0.3)
        real = MIDDLE + 45_000.0 - radio.state()["rxCorr"] + 150.0
        sc = win.wide
        x = int(round(sc.fmap.x(real)))
        QTest.mouseClick(sc, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(x, int(sc.r_spec.center().y())))
        menu = win.scope_menu_open
        acts = [a.text() for a in menu.actions()]
        # Beside a beacon, beacon lock comes first; auto-tune (USB) last.
        self.assertEqual(acts, ["Lock to this as the lower beacon", "Lock to this as the middle beacon",
                                "Lock to this as the upper beacon", "Auto-tune onto the voice here"])
        self.assertEqual(menu.defaultAction().text(), "Lock to this as the middle beacon")
        menu.defaultAction().trigger()
        menu.close()
        ok = self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked"
                          and abs(radio.state()["rxCorr"] - 45_000.0) < 5.0, timeout=20)
        self.assertTrue(ok, radio.state()["rxCorr"])
        self.assertTrue(any("set where you clicked" in t.text for t in win.toasts.toasts))

    def test_h_holds_and_says_so_everywhere(self):
        win, bridge, radio = self.window()
        self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked", timeout=20)
        win.wide.setFocus()
        QTest.keyClick(win, "h")
        self.run_for(radio, until=lambda: bridge.st.get("rxLock") == "hold", timeout=5)
        self.assertEqual(radio.state()["beaconMode"], "hold")
        b = win.rx_badge
        self.assertEqual((b.state, b.detail), ("hold", "no tracking"))
        self.assertIn(("Mode", "Hold — drift not followed"), b.rows)
        self.assertIn("(held)", " ".join(t for t, _c in win.status_items(bridge.st)))
        QTest.keyClick(win, "h")
        self.run_for(radio, until=lambda: radio.state()["beaconMode"] == "auto", timeout=5)
        listed = {k for _t, rows in win.overlay.sections for k, _w in rows}
        self.assertIn("H", listed)

    def test_manual_from_the_badge_nudge_type_and_wheel(self):
        win, bridge, radio = self.window()
        self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked", timeout=20)
        b = win.rx_badge
        # In Auto the wheel changes nothing and says why.
        c0 = radio.state()["rxCorr"]
        wheel(b, up=True)
        self.assertTrue(any("Manual only" in t.text for t in win.toasts.toasts))
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        pop = b.pop
        self.assertTrue(pop.isVisible())
        self.assertFalse(pop.manual.isVisible())
        pick = pop.mode
        QTest.mouseClick(pick, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         pick._cell(2).center().toPoint())
        self.run_for(radio, until=lambda: bridge.st.get("rxLock") == "manual", timeout=5)
        self.assertTrue(pop.manual.isVisible())
        c0 = radio.state()["rxCorr"]
        plus100 = pop.nudge_buttons[3]
        QTest.mouseClick(plus100, Qt.MouseButton.LeftButton)
        self.assertAlmostEqual(radio.state()["rxCorr"], c0 + 100.0, delta=0.05)
        # The wheel over the badge (the panel closed: an open popup takes
        # the wheel itself, as Qt's popups do).
        pop.hide()
        wheel(b, up=False)
        self.assertAlmostEqual(radio.state()["rxCorr"], c0 + 90.0, delta=0.05)
        wheel(b, up=True, shift=True)
        self.assertAlmostEqual(radio.state()["rxCorr"], c0 + 91.0, delta=0.05)
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        self.assertTrue(pop.isVisible() and pop.manual.isVisible())
        pop.field.setFocus()
        pop.field.setText("-27.454k")
        QTest.keyClick(pop.field, Qt.Key.Key_Return)
        self.assertEqual(radio.state()["rxCorr"], -27_454.0)
        self.assertTrue(radio.state()["rxCorrHand"])
        self.run_for(radio, 0.5)
        self.assertEqual(radio.state()["rxCorr"], -27_454.0)     # Manual: nothing moves it back
        pop.hide()


if __name__ == "__main__":
    unittest.main()
