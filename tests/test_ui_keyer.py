"""The voice keyer and CW memories from the window, on the simulator: the
F-keys send voice memory n in the voice modes and macro n in CW, only with
their buttons in view; Escape stops a CQ loop that is waiting; the licence
tick gates a memory as it gates PTT; the editor imports a WAV and records
from the radio's microphone."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import time
import unittest
import wave

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from test_ui_window import WindowCase

RATE = 12_000


def tone(seconds, hz=800.0):
    t = np.arange(int(seconds * RATE)) / RATE
    return (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class FunctionKeys(WindowCase):
    def voice_window(self, licence=True, **over):
        from ohscore.ui.panels.voice import VoicePanel
        # callsign + licenceClass: a known licence (QO-100 allowed under
        # Ofcom Full), so the "licence" standing warning (no class set)
        # does not keep the transmit card non-empty once the keyer's own
        # warning clears.
        over.setdefault("callsign", "GM4BRI")
        over.setdefault("licenceClass", "full")
        win, bridge, radio = self.window(licence=licence, mode="usb", vfo=10_489_700_000.0, **over)
        self.run_for(radio, until=lambda: isinstance(win.panel, VoicePanel), timeout=5)
        sent = []
        orig = radio.send_voice

        def send_voice(slot, _repeat=False):
            sent.append(slot)
            return orig(slot, _repeat)
        radio.send_voice = send_voice
        return win, bridge, radio, sent

    def test_f_keys_send_voice_memories_in_the_voice_modes(self):
        win, bridge, radio, sent = self.voice_window()
        # 2 s: the simulator sends faster than real time, and a 0.5 s memory
        # was on the air for about a tenth of a second - on a busy host the
        # window's 30 Hz pump could miss the whole over, the line set and
        # cleared within one tick (the pump hands on the latest state).
        radio.keyer.slots.store(1, tone(2.0))
        radio.keyer.slots.rename(1, "CQ")
        win.panel.keyer.rebuild()
        self.assertEqual(win.panel.keyer.buttons[1].text, "F2  CQ")
        # The transmit card says what is going out (its standing line), and
        # nothing once it has gone. Every line the card is given is noted as
        # it shows it, rather than sampling the label between event-loop
        # passes, which can fall either side of a short over.
        seen = set()
        warning = win.txcard.warning
        show = warning.set_warning

        def set_warning(w):
            show(w)
            seen.add(warning.text())
        warning.set_warning = set_warning
        win.activateWindow()
        QTest.keyClick(win, Qt.Key.Key_F2)
        self.assertEqual(sent, [1])

        def card():
            return not radio.state()["keyed"] and warning.text() == ""
        self.assertTrue(self.run_for(radio, until=card, timeout=10))
        self.assertIn("Sending voice memory 2: CQ", seen)
        # An empty slot is not sent: it says so instead.
        toasts = []
        bridge.toast.connect(toasts.append)
        QTest.keyClick(win, Qt.Key.Key_F1)
        self.assertEqual(sent, [1])
        self.assertIn("Voice memory 1 is empty", toasts[-1]["text"])
        # Not with the buttons out of sight.
        win.show_view("log")
        self.app.processEvents()
        QTest.keyClick(win, Qt.Key.Key_F2)
        self.assertEqual(sent, [1])

    def test_f_keys_in_cw_still_send_cw_memories_with_their_fields(self):
        from ohscore.ui.panels.text import TextPanel
        win, bridge, radio = self.window(mode="cw", vfo=10_489_520_000.0, callsign="GM4BRI", locator="IO86ha")
        self.run_for(radio, until=lambda: isinstance(win.panel, TextPanel), timeout=5)
        win.prefs["cwMacros"] = ["{DXCALL} DE {MYCALL} {LOC} K"]
        win.panel.macros.rebuild()
        win.activateWindow()
        toasts = []
        bridge.toast.connect(toasts.append)
        QTest.keyClick(win, Qt.Key.Key_F1)          # no DX call yet: not sent
        self.assertEqual(win.panel.txq.pending, "")
        self.assertIn("their call", toasts[-1]["text"])
        win.panel.qso.call.setText("dl1abc")
        QTest.keyClick(win, Qt.Key.Key_F1)
        self.assertEqual(win.panel.txq.pending, "DL1ABC DE GM4BRI IO86ha K ")
        win.panel.txq.clear()

    def test_the_licence_tick_gates_a_memory(self):
        from helpers import RadiatingSim
        from ohsnb.devices.sim import SimDevice
        win, bridge, radio, sent = self.voice_window(licence=False, device=type("R", (RadiatingSim, SimDevice), {}))
        radio.keyer.slots.store(0, tone(0.5))
        win.panel.keyer.rebuild()
        win.activateWindow()
        QTest.keyClick(win, Qt.Key.Key_F1)
        self.assertEqual(sent, [])
        self.assertFalse(radio.state()["keyed"])

    def test_escape_stops_a_waiting_cq_loop(self):
        win, bridge, radio, sent = self.voice_window(keyerRepeat=True, keyerRepeatSec=3.0)
        radio.keyer.slots.store(0, tone(0.3))
        win.panel.keyer.rebuild()
        self.assertTrue(win.panel.keyer.repeat.on)
        win.activateWindow()
        QTest.keyClick(win, Qt.Key.Key_F1)
        self.run_for(radio, until=lambda: radio.keyer.due(time.monotonic()) is not None, timeout=10)
        self.run_for(radio, until=lambda: "again in" in win.txcard.warning.text(), timeout=5)
        QTest.keyClick(win, Qt.Key.Key_Escape)
        self.assertFalse(radio.keyer.looping())
        self.run_for(radio, until=lambda: win.txcard.warning.text() == "", timeout=5)
        self.run_for(radio, 0.0, until=lambda: False, timeout=3.5)
        self.assertEqual(sent, [0])


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Editor(WindowCase):
    def test_import_a_wav_and_record_from_the_microphone(self):
        from ohscore.ui.keyer import VoiceKeyerDialog
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, 0.2)
        d = VoiceKeyerDialog(bridge, win)
        try:
            p = os.path.join(self.tmp, "cq.wav")
            with wave.open(p, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes((tone(1.0) * 32767).astype("<i2").tobytes())   # 12k samples = 1.5 s at 8 kHz
            self.assertTrue(d.import_file(2, p))
            self.assertAlmostEqual(radio.keyer.slots.seconds(2), 1.5, delta=0.02)
            self.assertEqual(d.rows[2]["length"].text(), "1.5 s")
            d.rows[2]["name"].setText("CQ contest")
            d.rows[2]["name"].editingFinished.emit()
            self.assertEqual(radio.keyer.slots.label(2), "CQ contest")
            # Record: the window's radio has a steady 0.2 mic (test_ui_window).
            # That mic is faster than real time, which would let the recording
            # reach its two-minute limit, and the dialog's tick collect it,
            # before a starved test thread got to press Stop - the press then
            # rightly started a new recording (the nightly, under an ISO
            # build). Pacing it in real time makes this the press-Stop case
            # it means to be; ending by itself is the next test's.
            radio.keyer.engine.audio.realtime = True
            QTest.mouseClick(d.rows[0]["rec"], Qt.MouseButton.LeftButton)
            self.assertEqual(d.rows[0]["rec"].text, "Stop")
            self.assertFalse(d.rows[1]["rec"].isEnabled())       # one at a time
            self.assertTrue(self.run_for(radio, 0.0, until=lambda: radio.keyer.recording() is not None
                                         and radio.keyer.recording()["seconds"] > 0.5, timeout=10))
            QTest.mouseClick(d.rows[0]["rec"], Qt.MouseButton.LeftButton)
            self.assertGreater(radio.keyer.slots.seconds(0), 0.3)
            self.assertAlmostEqual(float(np.mean(radio.keyer.slots.load(0))), 0.2, places=3)
            self.assertFalse(radio.state()["keyed"])
            self.assertIn("Recorded", d.status.text())
        finally:
            d.done(0)

    def test_stop_after_a_recording_ended_by_itself_does_not_start_another(self):
        # The window's microphone runs faster than real time, so a recording
        # reaches its two-minute limit in a fraction of a second. Waiting for
        # that without letting the dialog tick leaves its button saying Stop,
        # as an operator would see it for up to a tick after the limit.
        from ohscore.ui.keyer import VoiceKeyerDialog
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, 0.2)
        d = VoiceKeyerDialog(bridge, win)
        try:
            QTest.mouseClick(d.rows[0]["rec"], Qt.MouseButton.LeftButton)
            self.assertEqual(d.rows[0]["rec"].text, "Stop")
            end = time.monotonic() + 20
            while radio.keyer.recording() is not None and time.monotonic() < end:
                time.sleep(0.01)
            self.assertIsNone(radio.keyer.recording())
            self.assertEqual(d.rows[0]["rec"].text, "Stop")
            QTest.mouseClick(d.rows[0]["rec"], Qt.MouseButton.LeftButton)
            self.assertIsNone(radio.keyer.recording())
            self.assertIn("Recorded", d.status.text())
            self.assertEqual(d.rows[0]["rec"].text, "Record")
            self.assertGreater(radio.keyer.slots.seconds(0), 0.3)
        finally:
            d.done(0)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class HamFm(unittest.TestCase):
    """HAM's FM panel is its own (ohsradio/ui/fm.py): the keyer row is there
    too, and F1 sends through HAM's guard - with no licence class chosen,
    refused with its sentence and nothing keyed."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def run_window(self, licence_class):
        import tempfile
        from ham_helpers import make_radio
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(tempfile.mkdtemp(), "ui.json")
        radio = make_radio(licenceClass=licence_class, mode="fm", vfo=145_500_000.0)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.addCleanup(lambda: (win.close(), bridge.stop(), radio._tmp.cleanup()))
        radio.keyer.slots.store(0, tone(0.4))
        return win, bridge, radio

    def settle(self, cond, sec=10.0):
        end = time.monotonic() + sec
        while time.monotonic() < end and not cond():
            self.app.processEvents()
            time.sleep(0.01)
        return cond()

    def test_f1_in_fm_sends_through_the_licence_guard(self):
        from ohsradio.ui.fm import FmPanel
        win, bridge, radio = self.run_window("")
        self.assertTrue(self.settle(lambda: isinstance(win.panel, FmPanel) and win.panel.keyer.isVisible()))
        win.panel.keyer.rebuild()
        toasts = []
        bridge.toast.connect(toasts.append)
        win.activateWindow()
        self.settle(lambda: win.isActiveWindow(), 2.0)
        QTest.keyClick(win, Qt.Key.Key_F1)
        self.settle(lambda: toasts)
        self.assertFalse(radio.state()["keyed"])
        self.assertTrue(any("No licence class chosen" in t["text"] for t in toasts), toasts)
        radio.set(authorise=True, licenceClass="full")
        sources = []
        orig = radio._status

        def status(**kv):
            if kv.get("txSource"):
                sources.append(kv["txSource"])
            orig(**kv)
        radio._status = status
        QTest.keyClick(win, Qt.Key.Key_F1)
        self.assertTrue(self.settle(lambda: sources and not radio.state()["keyed"]), toasts)
        self.assertEqual(sources, ["voice:1"])


if __name__ == "__main__":
    unittest.main()
