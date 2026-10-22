"""Sound devices whose names Windows cuts short (ohscore/audio.py
list_devices, same_device, display_name; the pickers in Settings › Audio
and NB's IC-9700 page).

Windows' MME API, the one offered there, gives a device's name in at most
31 characters: Brian's work PC (17/10/2026) listed "Speakers (USB Audio
CODEC Analo" with its bracket left open. WASAPI lists the same endpoint
by its whole name. PortAudio is replaced here by a stand-in listing what
that PC's would: each endpoint under MME (cut) and WASAPI (whole)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from ohscore import audio
from systems import system

MME, WASAPI = 0, 1
SPEAKERS = "Speakers (USB Audio CODEC Analog Stereo)"
MIC = "Microphone (Realtek(R) Audio)"          # 29 characters: never cut
LINE = "Line In (High Definition Audio Device)"
JABRA = "Headset Earphone (Jabra EVOLVE 30 II)"[:31]      # "...EVOLVE ", the cut lands on a space


def dev(name, api, ins, outs):
    return {"name": name, "hostApi": api, "maxInputChannels": ins, "maxOutputChannels": outs,
            "defaultSampleRate": 48000.0}


DEVICES = [dev(SPEAKERS[:31], MME, 0, 2), dev(MIC, MME, 2, 0), dev(LINE[:31], MME, 2, 0),
           dev(SPEAKERS, WASAPI, 0, 2), dev(MIC, WASAPI, 2, 0), dev(LINE, WASAPI, 2, 0),
           # One only MME knows of: its whole name cannot be learnt.
           dev(JABRA, MME, 0, 2)]


class FakePa:
    paWASAPI = 13

    def __init__(self, devices=DEVICES):
        self.devices = devices

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, i):
        return dict(self.devices[i])

    def get_default_host_api_info(self):
        return {"index": MME}

    def get_host_api_info_by_type(self, t):
        if t != self.paWASAPI:
            raise OSError("no such host API")
        return {"index": WASAPI}

    def terminate(self):
        pass


def pyaudio_module():
    return types.SimpleNamespace(PyAudio=FakePa, paWASAPI=FakePa.paWASAPI)


class Names(unittest.TestCase):
    def listed(self, name="windows"):
        with system(name), mock.patch.dict(sys.modules, {"pyaudio": pyaudio_module()}):
            return {d["name"]: d for d in audio.list_devices()}

    def test_windows_names_are_made_whole_from_wasapi(self):
        got = self.listed()
        self.assertEqual(sorted(got), sorted([SPEAKERS[:31], MIC, LINE[:31], JABRA]))
        self.assertEqual((got[SPEAKERS[:31]]["full"], got[SPEAKERS[:31]]["label"]), (SPEAKERS, SPEAKERS))
        self.assertEqual(got[LINE[:31]]["full"], LINE)
        self.assertEqual((got[MIC]["full"], got[MIC]["label"]), (MIC, MIC))
        # Not known whole: shown cut, and saying so, brackets balanced.
        self.assertEqual(got[JABRA]["full"], JABRA)
        self.assertEqual(got[JABRA]["label"], "Headset Earphone (Jabra EVOLVE…)")

    def test_elsewhere_names_are_as_listed(self):
        for name in ("linux", "macos"):
            got = self.listed(name)
            # Every host API offered off Windows, and nothing renamed.
            self.assertEqual(got[SPEAKERS]["full"], SPEAKERS)
            self.assertEqual(got[SPEAKERS[:31]]["label"], SPEAKERS[:31] + "…)")    # an open bracket still closed

    def test_display_name(self):
        self.assertEqual(audio.display_name("Speakers (USB Audio CODEC Analo"), "Speakers (USB Audio CODEC Analo…)")
        self.assertEqual(audio.display_name("Mic ((nested"), "Mic ((nested…))")
        self.assertEqual(audio.display_name(MIC), MIC)
        self.assertEqual(audio.display_name("Exactly thirty-one characters!!", cut=True),
                         "Exactly thirty-one characters!!…")

    def test_same_device_by_whole_or_cut_name(self):
        self.assertTrue(audio.same_device(SPEAKERS, SPEAKERS[:31]))          # saved whole, listed cut
        self.assertTrue(audio.same_device(SPEAKERS[:31], SPEAKERS[:31]))     # saved cut (before 17/10)
        self.assertTrue(audio.same_device(SPEAKERS.upper(), SPEAKERS))
        self.assertFalse(audio.same_device(SPEAKERS, "Speakers (USB"))       # a short name is not a cut one
        self.assertFalse(audio.same_device("", SPEAKERS))
        self.assertFalse(audio.same_device("Speakers (USB Audio CODEC Analog Mono)", "Speakers (USB Audio CODEC Analog"))

    def test_the_backend_opens_the_device_saved_by_its_whole_name(self):
        with system("windows"), mock.patch.dict(sys.modules, {"pyaudio": pyaudio_module()}):
            b = audio.PortAudio(out_name=SPEAKERS, in_name=LINE)
            b.pa = FakePa()
            self.assertEqual(b._find(SPEAKERS, inputs=False), 0)            # MME's, not WASAPI's
            self.assertEqual(b._find(LINE, inputs=True), 2)
            self.assertEqual(b._find(SPEAKERS[:31], inputs=False), 0)
            self.assertEqual(b.notes, [])


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Pickers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def dialog(self, **saved):
        from helpers import make_radio
        from ohscore.ui.bridge import Bridge
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui.face import Qo100Face
        from ohsnb.ui.settings import SettingsDialog
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.environ["OHS_NB_UI_CONF"] = os.path.join(tmp, "ui.json")
        radio = make_radio(tmp, **saved)
        bridge = Bridge(radio, face=Qo100Face())
        self.addCleanup(lambda: [radio.unsubscribe(f) for f in bridge.feeds.values()])
        with system("windows"), mock.patch.dict(sys.modules, {"pyaudio": pyaudio_module()}), \
                mock.patch.object(audio, "default_devices",
                                  lambda: {"input": MIC, "output": SPEAKERS, "error": ""}):
            d = SettingsDialog(bridge, Prefs(config.CONFIG))
            d._fill_rig_audio()
        self.addCleanup(d.close)
        return d

    def items(self, cb):
        from PyQt6.QtCore import Qt
        return [(cb.itemText(i), cb.itemData(i), cb.itemData(i, Qt.ItemDataRole.ToolTipRole))
                for i in range(cb.count())]

    def test_whole_names_shown_saved_and_in_the_tooltip(self):
        d = self.dialog(audioOut=SPEAKERS)
        out = d.audio_combos["audioOut"]
        self.assertIn((SPEAKERS, SPEAKERS, SPEAKERS), self.items(out))
        self.assertIn(("Headset Earphone (Jabra EVOLVE…)", JABRA, JABRA), self.items(out))
        self.assertEqual(out.currentData(), SPEAKERS)
        self.assertIn((LINE, LINE, LINE), self.items(d.audio_combos["audioIn"]))
        self.assertIn((SPEAKERS, SPEAKERS, SPEAKERS), self.items(d.rig_audio))

    def test_a_choice_saved_by_its_cut_name_is_still_chosen(self):
        d = self.dialog(audioOut=SPEAKERS[:31], audioIn=LINE[:31], rigTxAudioOut=SPEAKERS[:31])
        self.assertEqual(d.audio_combos["audioOut"].currentData(), SPEAKERS)
        self.assertEqual(d.audio_combos["audioIn"].currentData(), LINE)
        self.assertEqual(d.rig_audio.currentData(), SPEAKERS)
        self.assertFalse([t for t, _d, _t in self.items(d.audio_combos["audioOut"]) if "not connected" in t])

    def test_a_missing_device_keeps_its_place_with_balanced_brackets(self):
        d = self.dialog(audioOut="Speakers (Some Long USB Headset")
        cb = d.audio_combos["audioOut"]
        self.assertEqual(cb.currentText(), "Speakers (Some Long USB Headset…) (not connected)")
        self.assertEqual(cb.currentData(), "Speakers (Some Long USB Headset")


if __name__ == "__main__":
    unittest.main()
