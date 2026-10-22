"""The CW panel's "Decoder hears N wpm" goes back to "Decoder speed —" when
the decoder stops hearing anyone (its squelch closes, shack_cw
Decoder.hearing), instead of keeping the last station's speed for good.

The decoder speaks only when it prints a letter, so the engine carries
`hearing` in the meter feed as `cwHearing` while in CW; the panel clears on
False. These run the window on the simulator: the speed arrives as the
decoder's own event would, and the meter that clears it comes from the
real engine with a real CW decoder listening to a quiet stretch of band."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

import ham_helpers
from test_ui_window import WindowCase

IDLE = "Decoder speed —"
# Between the lower beacon (10 489.500) and the simulator's stations: no
# keying here for the decoder to hear.
QUIET = 10_489_610_000.0


def speed_event(wpm: float) -> dict:
    """A letter as shack_cw's decoder emits it (its _emit)."""
    return {"mode": "cw", "text": "E", "freq": 700.0, "wpm": wpm}


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class DecoderSpeedLabel(WindowCase):
    def cw_window(self):
        from ohscore.ui.panels.text import TextPanel
        win, bridge, radio = self.window(mode="cw", vfo=QUIET)
        self.assertTrue(self.run_for(radio, until=lambda: isinstance(win.panel, TextPanel)
                                     and radio.decoder is not None, timeout=10))
        return win, bridge, radio

    def test_speed_clears_when_the_decoder_stops_hearing(self):
        win, bridge, radio = self.cw_window()
        meters = []
        bridge.meter.connect(meters.append)
        win.on_event(speed_event(22.4))
        self.assertEqual(win.panel.heard.text(), "Decoder hears 22 wpm")
        self.assertTrue(self.run_for(radio, until=lambda: win.panel.heard.text() == IDLE, timeout=10),
                        f"label stayed at {win.panel.heard.text()!r}")
        self.assertIn(False, [m.get("cwHearing") for m in meters])

    def test_speed_stays_while_the_decoder_hears(self):
        win, bridge, radio = self.cw_window()
        win.on_event(speed_event(18.0))
        # A meter that says the squelch is open, or one from before the CW
        # decoder existed (no cwHearing), leaves the speed alone.
        win.panel.on_meter({"rx": -60.0, "cwHearing": True})
        win.panel.on_meter({"rx": -60.0})
        self.assertEqual(win.panel.heard.text(), "Decoder hears 18 wpm")


class MeterCarriesHearing(unittest.TestCase):
    """Radio's engine: cwHearing in CW only, never in another mode, where
    the meter must stay as it was for every client that reads it."""

    def meters(self, mode):
        r = ham_helpers.make_radio(mode=mode)
        feed = r.subscribe("meter", 256)
        try:
            r.start()
            try:
                return ham_helpers.pump(r, 3.0, feeds=(feed,))["meter"]
            finally:
                r.stop()
        finally:
            r._tmp.cleanup()

    def test_cw_meter_says_whether_the_decoder_hears(self):
        ms = self.meters("cw")
        self.assertTrue(any("cwHearing" in m for m in ms), ms[:3])
        self.assertTrue(all(isinstance(m["cwHearing"], bool) for m in ms if "cwHearing" in m))

    def test_other_modes_have_no_cw_field(self):
        ms = self.meters("usb")
        self.assertTrue(ms)
        self.assertFalse(any("cwHearing" in m for m in ms))


if __name__ == "__main__":
    unittest.main()
