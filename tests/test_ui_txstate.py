"""The transmit card and the TX tile when transmitting is impossible, needs
setting up, or is refused here (docs/ui-overhaul-2026-10.md section 5.9),
in the real windows on the simulator and the IC-9700 emulator, on Qt's
offscreen platform: what the widgets show and that halting still halts.
Nothing here keys a real radio; the IC-9700 is ohscore/rig/civsim.py."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from helpers import RadiatingSim, rig_conv
from ohscore.config import RECEIVE_ONLY_REFUSAL, receive_only
from ohscore.rig.civsim import CivSim

from test_ui_window import WindowCase

LO = 1_104_000_000.0
# A station with its licence class chosen, so the only thing between it and
# transmitting is the acknowledgement box: no "no licence class" warning
# stands, and the card may collapse.
STATION = {"callsign": "GM4BRI", "licenceClass": "full"}


def radiating():
    from ohsnb.devices.sim import SimDevice

    class Radiating(RadiatingSim, SimDevice):
        pass
    return Radiating


def shows(card) -> str:
    """'short', 'full' or 'gone': what of the card is on screen."""
    if not card.isVisible():
        return "gone"
    if card.short.isVisible() and not card.body.isVisible():
        return "short"
    if card.body.isVisible() and not card.short.isVisible():
        return "full"
    return "both?"


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class NoTransmit(WindowCase):
    def test_receive_only_is_one_line_and_the_tile_says_so(self):
        over = {}
        receive_only(over)
        win, bridge, radio = self.window(mode="usb", vfo=10_489_700_000.0, **over)
        self.run_for(radio, 0.5)
        card = win.txcard
        self.assertEqual(shows(card), "short")
        self.assertEqual(card.short_text.text(), "Receive only this run")
        self.assertEqual(card.short_text.toolTip(), RECEIVE_ONLY_REFUSAL)
        self.assertFalse(card.short_btn.isVisible())         # nothing in Settings changes it
        self.assertEqual(win.ptt.caption(), ("TX", "Receive only"))
        self.assertIn("This run cannot transmit", win.ptt.toolTip())
        self.assertIn(RECEIVE_ONLY_REFUSAL, win.ptt.toolTip())
        # Every form keeps the one line (or, in Watch, nothing).
        card.set_form("compact")
        self.assertEqual(shows(card), "short")
        card.set_form("hidden")
        self.assertEqual(shows(card), "gone")
        card.set_form("full")
        self.assertEqual(shows(card), "short")
        # The tile still answers a press, and nothing goes out.
        QTest.mousePress(win.ptt, Qt.MouseButton.LeftButton)
        self.run_for(radio, 0.2)
        QTest.mouseRelease(win.ptt, Qt.MouseButton.LeftButton)
        self.assertFalse(radio.state()["keyed"])

    def test_a_radio_without_the_licence_ticked_needs_setting_up(self):
        win, bridge, radio = self.window(licence=False, device=radiating(), mode="usb", vfo=10_489_700_000.0,
                                         **STATION)
        self.run_for(radio, 0.5)
        card = win.txcard
        self.assertEqual(shows(card), "short")
        self.assertEqual(card.short_text.text(), "Set up to transmit: Settings › Station")
        self.assertTrue(card.short_btn.isVisible())
        self.assertEqual(win.ptt.caption(), ("TX", "Set up to transmit"))
        with mock.patch.object(win, "open_settings") as opened:
            QTest.mouseClick(card.short_btn, Qt.MouseButton.LeftButton)
        opened.assert_called_once_with("page_station")
        # Ticking it in Settings brings the controls back.
        win.prefs["licenceAck"] = True
        win.apply_prefs(False)
        self.run_for(radio, 0.1)
        self.assertEqual(shows(card), "full")
        self.assertEqual(win.ptt.caption(), ("TX", "Space to talk"))

    def test_a_standing_warning_keeps_the_card_whole(self):
        win, bridge, radio = self.window(licence=False, device=radiating(), mode="usb", vfo=10_489_700_000.0,
                                         **STATION)
        self.run_for(radio, 0.3)
        card = win.txcard
        self.assertEqual(shows(card), "short")
        radio.tx_warn("test", "A warning that must be seen", "warn")
        self.assertTrue(self.run_for(radio, until=lambda: shows(card) == "full", timeout=5))
        self.assertTrue(card.warning.isVisible())
        card.set_form("hidden")
        self.assertEqual(shows(card), "full")
        radio.tx_clear("test")
        self.assertTrue(self.run_for(radio, until=lambda: shows(card) == "gone", timeout=5))


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class TileWords(WindowCase):
    def test_each_mode_says_how_it_transmits(self):
        win, bridge, radio = self.window(mode="usb", vfo=10_489_700_000.0)
        self.run_for(radio, 0.3)
        want = [("usb", 10_489_700_000.0, "Space to talk"), ("ft8", 10_489_540_000.0, "Enable TX below"),
                ("ft4", 10_489_545_000.0, "Enable TX below"), ("psk31", 10_489_545_000.0, "Type, Enter sends"),
                ("sstv", 10_489_900_000.0, "Send from the panel"), ("js8", 10_489_548_000.0, "Enable TX below")]
        for mode, vfo, words in want:
            bridge.set(mode=mode, vfo=vfo)
            self.run_for(radio, until=lambda: bridge.st.get("mode") == mode and
                         bridge.st.get("txBlocked") == radio.state()["txBlocked"], timeout=5)
            self.run_for(radio, 0.2)
            self.assertEqual(win.ptt.caption(), ("TX", words), (mode, radio.state()["txBlocked"]))
        self.assertEqual(shows(win.txcard), "full")

    def test_refused_here_says_why_in_a_few_words(self):
        win, bridge, radio = self.window(mode="usb", vfo=10_489_520_000.0)    # SSB in the CW segment
        self.run_for(radio, until=lambda: bridge.st.get("txBlocked"), timeout=5)
        self.run_for(radio, 0.2)
        self.assertEqual(win.ptt.caption(), ("TX", "Not in this segment"))
        self.assertIn(bridge.st["txBlocked"], win.ptt.toolTip())
        self.assertEqual(shows(win.txcard), "full")              # "here": everything stays
        bridge.set(mode="am")
        self.run_for(radio, until=lambda: "AM" in (bridge.st.get("txBlocked") or ""), timeout=5)
        self.run_for(radio, 0.2)
        self.assertEqual(win.ptt.caption(), ("TX", "Receive only"))

    def test_the_words_fit_the_tile_in_every_case(self):
        from PyQt6.QtGui import QFontMetricsF
        from ohscore.ui import theme
        win, bridge, radio = self.window(mode="usb", vfo=10_489_700_000.0)
        self.run_for(radio, 0.2)
        keys = ("talk", "enable", "type", "panel", "rxonly", "setup", "stopped", "dish", "onradio", "swr",
                "sequencer", "beacon", "wide", "segment", "band", "class", "licence", "power", "rate", "playing", "?")
        room = win.ptt.width() - 6 - 16
        for k in keys:
            fm = QFontMetricsF(theme.font(9.0, theme.QFont.Weight.DemiBold))
            self.assertLessEqual(fm.horizontalAdvance(win.ptt.words(k)), room, k)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Forms(WindowCase):
    def test_compact_drops_alc_and_the_level_sentence_until_on_the_air(self):
        win, bridge, radio = self.window(mode="usb", vfo=10_489_700_000.0)
        self.run_for(radio, 0.3)
        card = win.txcard
        card.set_form("compact")
        self.assertTrue(card.power.isVisible())
        self.assertTrue(card.beacon.isVisible())
        self.assertFalse(card.alc.isVisible())
        self.assertFalse(card.level.isVisible())
        bridge.ptt(True)                                  # the simulator: nothing radiates
        try:
            self.assertTrue(self.run_for(radio, until=lambda: card.alc.isVisible(), timeout=5))
            self.assertTrue(card.level.isVisible())
        finally:
            bridge.ptt(False)
        self.assertTrue(self.run_for(radio, until=lambda: not card.alc.isVisible(), timeout=5))
        card.set_form("full")
        self.assertTrue(card.alc.isVisible())

    def test_hidden_comes_back_while_keyed(self):
        win, bridge, radio = self.window(mode="usb", vfo=10_489_700_000.0, **STATION)
        self.run_for(radio, 0.3)
        card = win.txcard
        card.set_form("hidden")
        self.assertEqual(shows(card), "gone")
        bridge.ptt(True)
        try:
            self.assertTrue(self.run_for(radio, until=lambda: shows(card) == "full", timeout=5))
        finally:
            bridge.ptt(False)
        self.assertTrue(self.run_for(radio, until=lambda: shows(card) == "gone", timeout=5))
        # Escape halts from any form.
        bridge.ptt(True)
        self.assertTrue(self.run_for(radio, until=lambda: radio.state()["keyed"], timeout=5))
        QTest.keyClick(win, Qt.Key.Key_Escape)
        self.assertTrue(self.run_for(radio, until=lambda: not radio.state()["keyed"], timeout=5))


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class HandKeyedRig(WindowCase):
    """The safety rule's hardest case: a card that may collapse (the
    licence box unticked with a radio), and an IC-9700 keyed at its own
    microphone, which NB cannot stop and did not key."""

    def setUp(self):
        super().setUp()
        self.civ = CivSim(freq=1_296_190_000).start()
        self.addCleanup(self.civ.stop)

    def tearDown(self):
        self.assertEqual(self.civ.ptt_commands(), [])          # NB never keyed it
        super().tearDown()

    def test_a_9700_keyed_by_hand_brings_the_card_back_in_full(self):
        win, bridge, radio = self.window(licence=False, device=radiating(), txRadio="civ", civPort=self.civ.url,
                                         **rig_conv(LO), rigPollMs=50, **STATION)
        card = win.txcard
        self.assertTrue(self.run_for(radio, until=lambda: bridge.st.get("rigLink") == "ok", timeout=10))
        self.run_for(radio, 0.2)
        self.assertEqual(shows(card), "short")
        self.civ.key(True)
        self.assertTrue(self.run_for(radio, until=lambda: shows(card) == "full", timeout=5))
        self.assertTrue(card.rig.text().endswith("TX"))
        card.set_form("hidden")
        self.assertEqual(shows(card), "full")                   # Watch too
        card.set_form("compact")
        self.assertEqual(shows(card), "full")
        # Aimed into the middle beacon while keyed: the warning is there to read.
        self.civ.turn(int(__import__("ohsnb.bandplan", fromlist=["ul"]).ul(10_489_748_000.0) - LO))
        self.assertTrue(self.run_for(radio, until=lambda: card.warning.isVisible() or card.rig_warn.isVisible(),
                                     timeout=5))
        self.civ.key(False)
        self.civ.turn(int(__import__("ohsnb.bandplan", fromlist=["ul"]).ul(10_489_700_000.0) - LO))
        card.set_form("full")
        self.assertTrue(self.run_for(radio, until=lambda: shows(card) == "short", timeout=5))


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class RadioApp(WindowCase):
    def ham_window(self, **over):
        from ham_helpers import make_radio
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ham-ui.json")
        radio = make_radio(**over)
        self.addCleanup(radio._tmp.cleanup)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        return win, bridge, radio

    def test_radio_receive_only_is_one_line_and_compact_keeps_the_drive(self):
        over = {}
        receive_only(over)
        win, bridge, radio = self.ham_window(**over)
        self.run_for(radio, 0.3)
        self.assertEqual(shows(win.txcard), "short")
        self.assertEqual(win.ptt.caption(), ("TX", "Receive only"))
        win2, bridge2, radio2 = self.ham_window()
        self.run_for(radio2, 0.3)
        card = win2.txcard
        self.assertEqual(shows(card), "full")
        card.set_form("compact")
        self.assertTrue(card.drive.isVisible())
        self.assertFalse(card.swr.isVisible())
        self.assertFalse(card.alc.isVisible())
