"""Radio › Dish alignment… in the window (ohsnb/ui/dishmeter.py), against a
real Radio on the simulator, on Qt's offscreen platform: the menu opens it,
the big number is the engine's, the tone and the phone page are switched
from it, transmit is refused while it is open, it will not open while
transmitting, and closing it - by its button or with the main window -
ends the gain hold and the phone page."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import socket
import unittest
import urllib.request

from test_ui_window import HAVE_QT, WindowCase


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class DishFromTheWindow(WindowCase):
    def opened(self, **over):
        win, bridge, radio = self.window(**over)
        self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked")
        win.act_dish.trigger()
        d = win.dish_dialog
        self.assertIsNotNone(d)
        self.assertTrue(d.isVisible())
        self.run_for(radio, until=lambda: bridge.st.get("dishSnr") is not None)
        self.run_for(radio, sim_s=0.5)
        return win, bridge, radio, d

    def test_the_menu_opens_it_and_it_shows_the_engines_numbers(self):
        from ohsnb.ui.dishmeter import db_text
        win, bridge, radio, d = self.opened()
        self.assertTrue(radio.state()["dishOpen"])
        self.assertEqual(d.snr.text(), db_text(bridge.st["dishSnr"]))
        self.assertGreater(float(d.snr.text()), 20.0)
        self.assertIn("dB over the noise beside it", d.rise.text())
        self.assertIn("held at 40 dB", d.gain.text())
        # Again from the menu: the same window, brought forward.
        win.act_dish.trigger()
        self.assertIs(win.dish_dialog, d)
        d.reset_best()
        self.assertEqual(d.best.text(), "Best —")
        self.run_for(radio, until=lambda: bridge.st.get("dishBest") is not None)
        self.assertNotEqual(d.best.text(), "Best —")

    def test_tone_and_phone_page_are_switched_from_it_and_end_with_it(self):
        port = free_port()
        win, bridge, radio, d = self.opened(dishPort=port)
        d.tone.setChecked(True)
        self.assertTrue(radio.state()["dishTone"])
        self.assertFalse(d.urls.isVisible())
        d.phone.setChecked(True)
        self.run_for(radio, until=lambda: bool(bridge.st.get("dishUrls")))
        self.assertTrue(radio.state()["dishPhone"])
        self.assertIn(f":{port}/", d.urls.text())
        self.assertFalse(d.port.isEnabled())
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).read()
        self.assertIn(b"Middle beacon", page)
        d.close()
        self.app.processEvents()
        s = radio.state()
        self.assertFalse(s["dishOpen"])
        self.assertFalse(s["dishPhone"])
        self.assertIsNone(win.dish_dialog)
        with self.assertRaises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)

    def test_transmit_is_refused_while_open_and_it_will_not_open_while_transmitting(self):
        win, bridge, radio, d = self.opened(mode="cw", vfo=10_489_520_000.0)
        self.assertFalse(bridge.ptt(True))
        self.assertFalse(radio.state()["keyed"])
        self.run_for(radio, until=lambda: "Dish alignment is open" in (bridge.st.get("txBlocked") or ""))
        self.assertIn("Dish alignment is open", bridge.st["txBlocked"])
        d.close()
        self.app.processEvents()
        self.assertTrue(bridge.ptt(True))
        try:
            self.assertTrue(radio.state()["keyed"])
            win.act_dish.trigger()
            self.assertIsNone(win.dish_dialog)
            self.assertFalse(radio.state()["dishOpen"])
        finally:
            bridge.ptt(False)

    def test_closing_the_main_window_closes_it(self):
        win, bridge, radio, d = self.opened()
        win.close()
        self.app.processEvents()
        self.assertFalse(radio.state()["dishOpen"])


if __name__ == "__main__":
    unittest.main()
