"""Red means on the air, armed, our own signal over the beacon, LEILA or an
error, and nothing else (docs/ui-overhaul-2026-10.md section 5.3). These
paint the widgets that used to be red while receiving and look at the
pixels: none may be near the theme's transmit or error red while the
simulator receives with nothing armed, in either theme; then the simulator
is keyed and the TX tile, the readout and the S-meter's over-zone must turn
red. They run the paint, never read source. Later packages add their
widgets here (WP4 the QSO card, WP7 the scopes' TX marks)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import numpy as np
    from PyQt6.QtGui import QImage
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from test_ui_window import WindowCase

REDS = ("tx", "txGlow", "err")
NEAR = 40          # per channel: antialiasing of a neutral or amber edge never comes this close


def red_pixels(widget, rect=None, keys=REDS) -> int:
    """Pixels of `widget` (or of `rect` in it), as painted now, within NEAR
    of any red token of the current theme (or of the `keys` given)."""
    from ohscore.ui import theme
    img = (widget.grab(rect.toRect()) if rect is not None else widget.grab()).toImage().convertToFormat(
        QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    a = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w, :3].astype(int)
    rgb = a[..., ::-1]                                 # BGRA in memory
    n = 0
    for k in keys:
        c = theme.sc(k) if k == "own" else theme.c(k)
        ref = np.array([c.red(), c.green(), c.blue()])
        n += int((np.abs(rgb - ref).max(axis=-1) <= NEAR).sum())
    return n


def themes():
    from ohscore.ui import theme
    before = theme.t()["name"]
    try:
        for name in ("dark", "light"):
            theme.set_theme(name)
            yield name
    finally:
        theme.set_theme(before)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Receiving(WindowCase):
    def settle(self, meter, value_dbfs, beacon):
        meter.feed(value_dbfs, beacon)
        for _ in range(60):
            meter.tick(0.05)

    def test_nothing_is_red_while_receiving(self):
        win, bridge, radio = self.window(mode="usb", vfo=10_489_700_000.0, xitOn=True, xit=120.0)
        self.run_for(radio, 0.5)
        self.assertFalse(radio.state()["keyed"])
        self.assertIsNone(win.ptt.armed_at)
        m = win.rxcard.s
        for name in themes():
            # The S-meter at S9+40 against the beacon, in every style.
            for style in ("bar", "analog", "digital"):
                m.set_pref("sMeterStyle", style)
                self.settle(m, -40.0, -80.0)
                self.assertEqual(m.value_text(), "S9+40")
                self.assertEqual(red_pixels(m), 0, (name, style))
            win.ptt.update()
            self.assertEqual(red_pixels(win.ptt), 0, name)                     # the idle tile
            self.assertEqual(red_pixels(win.txcard.power), 0, name)            # fill and ceiling mark
            self.assertIsNotNone(win.txcard.power.cap)
            self.assertEqual(red_pixels(win.readout), 0, name)                 # XIT on, idle
            self.assertTrue(bridge.st.get("xitOn"))

    def test_sent_text_is_gold(self):
        from ohscore.ui.panels.common import Terminal
        for name in themes():
            t = Terminal()
            t.resize(400, 120)
            t.put("CQ CQ DE GM4BRI GM4BRI K", "tx")
            t.show()
            self.app.processEvents()
            self.assertEqual(red_pixels(t), 0, name)
            t.close()

    def test_radios_licence_chips_are_amber(self):
        from ham_helpers import make_radio
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ham-ui.json")
        for cls, word in (("", "NO CLASS"), ("foundation", "NO TX HERE")):
            radio = make_radio(licenceClass=cls)
            self.addCleanup(radio._tmp.cleanup)
            prefs = Prefs(config.CONFIG)
            prefs["welcomed"] = True
            prefs["licenceAck"] = True
            win, bridge = build(radio, prefs)
            win.resize(1600, 960)
            win.show()
            self.wins.append((win, bridge))
            if cls:
                radio.band("23cm")                        # no Foundation privileges there
                radio.set(mode="usb")
            self.run_for(radio, until=lambda: win.lic_chip.word == word, timeout=10)
            self.assertEqual(win.lic_chip.word, word)
            for name in themes():
                self.assertEqual(red_pixels(win.lic_chip), 0, (word, name))


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class ScopeTxMarks(WindowCase):
    """The TX marks on the scopes (WP7): the zoom's TX offset flag and band
    and the wide's TX line are our own signal's gold while receiving, red
    once keyed. Only the spectrum is looked at: the waterfall's palettes
    and the band plan's strip are data, and have reds of their own."""

    def test_gold_while_receiving_red_on_the_air(self):
        win, bridge, radio = self.window(mode="ft8", vfo=10_489_540_000.0)
        self.run_for(radio, 1.0)
        win.offset_click(900.0, True)                      # TX apart from RX, so its flag stands alone
        self.run_for(radio, 0.3)
        self.assertEqual(win.zoom.audio_offsets.get("tx"), 900.0)
        for name in themes():
            for sc in (win.wide, win.zoom):
                sc.repaint()
                self.assertEqual(red_pixels(sc, sc.r_spec), 0, (name, sc.kind))
            self.assertGreater(red_pixels(win.zoom, win.zoom.r_spec, keys=("own",)), 50, name)
        bridge.ptt(True)                                   # the simulator: nothing radiates
        try:
            self.assertTrue(self.run_for(radio, until=lambda: bridge.face.on_air(bridge.st), timeout=10))
            for name in themes():
                for sc in (win.wide, win.zoom):
                    sc.repaint()
                    self.assertGreater(red_pixels(sc, sc.r_spec), 50, (name, sc.kind))
        finally:
            bridge.ptt(False)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class OnTheAir(WindowCase):
    def test_keyed_the_tile_readout_and_s_meter_over_zone_turn_red(self):
        win, bridge, radio = self.window(mode="usb", vfo=10_489_700_000.0)
        self.run_for(radio, 0.5)
        m = win.rxcard.s
        bridge.ptt(True)                                  # the simulator: nothing radiates
        try:
            self.assertTrue(self.run_for(radio, until=lambda: bridge.face.on_air(bridge.st)
                                         and win.ptt.on.value > 0.95, timeout=10))
            for name in themes():
                win.ptt.update()
                self.assertGreater(red_pixels(win.ptt), 200, name)
                self.assertGreater(red_pixels(win.readout), 20, name)
                for style in ("bar", "analog", "digital"):
                    m.set_pref("sMeterStyle", style)
                    m.feed(-40.0, -80.0)
                    for _ in range(60):
                        m.tick(0.05)
                    self.assertTrue(m.on_air)
                    self.assertGreater(red_pixels(m), 10, (name, style))
        finally:
            bridge.ptt(False)
        self.assertTrue(self.run_for(radio, until=lambda: not bridge.face.on_air(bridge.st), timeout=10))
        m.feed(-40.0, -80.0)
        for _ in range(60):
            m.tick(0.05)
        self.assertFalse(m.on_air)
        self.assertEqual(red_pixels(m), 0)                 # back to neutral once off the air
