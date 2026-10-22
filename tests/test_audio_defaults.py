"""What "System default" means, shown in Settings › Audio: the device
each system's default resolves to (ohscore/audio.py default_devices, with
the Linux sound-server lookup in ohscore/host.py), and the pickers saying
it, refreshed on Look again. PortAudio is replaced by a stand-in with the
answers each system gives, and pactl by its recorded output, so every
system's case runs here; the pickers are driven in a real Settings
dialog."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import subprocess
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

from ohscore import audio, host
from systems import system

# `pactl info` and `pactl list sinks` from the PipeWire laptop (Debian 13,
# 08/10/2026), cut down: the default is the second sink, not the first.
PACTL_INFO = """Server String: /run/user/1000/pulse/native
Server Name: PulseAudio (on PipeWire 1.4.2)
Default Sample Specification: float32le 2ch 48000Hz
Default Sink: alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink
Default Source: alsa_input.usb-Burr-Brown_USB_Audio_CODEC-00.analog-stereo
"""
PACTL_SINKS = """Sink #52
	State: SUSPENDED
	Name: alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__HDMI1__sink
	Description: Tiger Lake-LP Smart Sound Technology Audio Controller HDMI / DisplayPort 1 Output
Sink #53
	State: RUNNING
	Name: alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink
	Description: Tiger Lake-LP Smart Sound Technology Audio Controller Speaker
"""
PACTL_SOURCES = """Source #60
	Name: alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink.monitor
	Description: Monitor of Tiger Lake-LP Smart Sound Technology Audio Controller Speaker
Source #61
	Name: alsa_input.usb-Burr-Brown_USB_Audio_CODEC-00.analog-stereo
	Description: USB Audio CODEC Analog Stereo
"""


def fake_pactl(answers=None, fail=False):
    """subprocess.run as pactl would answer it."""
    answers = answers or {("info",): PACTL_INFO, ("list", "sinks"): PACTL_SINKS, ("list", "sources"): PACTL_SOURCES}
    calls = []

    def run(argv, **kw):
        calls.append((tuple(argv[1:]), kw.get("env", {}).get("LC_ALL")))
        if fail:
            raise subprocess.TimeoutExpired(argv, 2)
        return subprocess.CompletedProcess(argv, 0, answers.get(tuple(argv[1:]), ""), "")
    return run, calls


class SoundServer(unittest.TestCase):
    def lookup(self, output, run, which="/usr/bin/pactl", name="linux"):
        with system(name), mock.patch.object(shutil, "which", return_value=which), \
                mock.patch.object(subprocess, "run", run):
            return host.sound_server_default(output)

    def test_names_the_device_behind_the_default(self):
        run, calls = fake_pactl()
        self.assertEqual(self.lookup(True, run), "Tiger Lake-LP Smart Sound Technology Audio Controller Speaker")
        self.assertEqual(self.lookup(False, run), "USB Audio CODEC Analog Stereo")
        # Asked in the C locale: the field names it reads are English.
        self.assertTrue(all(lc == "C" for _a, lc in calls))

    def test_without_pactl_or_an_answer_says_nothing(self):
        run, _ = fake_pactl()
        self.assertIsNone(self.lookup(True, run, which=None))
        run, _ = fake_pactl(fail=True)
        self.assertIsNone(self.lookup(True, run))
        run, _ = fake_pactl({("info",): "Server Name: PulseAudio\n"})      # no default sink at all
        self.assertIsNone(self.lookup(True, run))

    def test_a_default_with_no_description_is_shown_by_its_name(self):
        run, _ = fake_pactl({("info",): PACTL_INFO, ("list", "sinks"): ""})
        self.assertEqual(self.lookup(True, run),
                         "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink")

    def test_never_asked_on_windows_or_macos(self):
        run, calls = fake_pactl()
        for name in ("windows", "macos"):
            self.assertIsNone(self.lookup(True, run, name=name))
        self.assertEqual(calls, [])


class FakePyAudio:
    """PortAudio as pyaudio shows it: the default input and output (None
    for "there is none", which PortAudio reports by raising), every
    device by index, and WASAPI's own defaults on Windows."""
    paWASAPI = 13
    instances = []

    def __init__(self, inp, out, devices=(), wasapi=None):
        self.inp, self.out, self.devices, self.wasapi = inp, out, list(devices), wasapi
        self.terminated = False

    def _info(self, name):
        if name is None:
            raise OSError("No Default Device Available")
        return {"name": name}

    def get_default_input_device_info(self):
        return self._info(self.inp)

    def get_default_output_device_info(self):
        return self._info(self.out)

    def get_device_info_by_index(self, i):
        return {"name": self.devices[i]}

    def get_host_api_info_by_type(self, t):
        if t != self.paWASAPI or self.wasapi is None:
            raise OSError("no such host API")
        return {"defaultInputDevice": self.wasapi[0], "defaultOutputDevice": self.wasapi[1]}

    def terminate(self):
        self.terminated = True


def pyaudio_module(*a, **kw):
    made = []

    def factory():
        pa = FakePyAudio(*a, **kw)
        made.append(pa)
        return pa
    mod = types.SimpleNamespace(PyAudio=factory, paWASAPI=FakePyAudio.paWASAPI)
    return mod, made


class Defaults(unittest.TestCase):
    def resolve(self, mod, name="linux", server=None):
        with system(name), mock.patch.dict(sys.modules, {"pyaudio": mod}), \
                mock.patch.object(host, "sound_server_default", lambda output: server[output] if server else None):
            return audio.default_devices()

    def test_a_named_default_is_shown_as_it_is(self):
        mod, made = pyaudio_module("USB Audio CODEC: - (hw:2,0)", "HD-Audio Generic: ALC269VC Analog (hw:1,0)")
        got = self.resolve(mod)
        self.assertEqual(got, {"input": "USB Audio CODEC: - (hw:2,0)",
                               "output": "HD-Audio Generic: ALC269VC Analog (hw:1,0)", "error": ""})
        self.assertTrue(made[0].terminated)

    def test_the_sound_server_is_asked_what_default_means(self):
        mod, _ = pyaudio_module("default", "pulse")
        got = self.resolve(mod, server={False: "USB Audio CODEC Analog Stereo", True: "Built-in Speaker"})
        self.assertEqual((got["input"], got["output"]), ("USB Audio CODEC Analog Stereo", "Built-in Speaker"))

    def test_when_the_server_will_not_say_its_own_word_is_shown(self):
        mod, _ = pyaudio_module("default", "pulse")
        got = self.resolve(mod)
        self.assertEqual((got["input"], got["output"]), ("default", "pulse"))

    def test_no_default_of_a_kind_is_none(self):
        mod, _ = pyaudio_module(None, "Speakers")
        got = self.resolve(mod, name="macos")
        self.assertEqual((got["input"], got["output"], got["error"]), (None, "Speakers", ""))

    def test_windows_sound_mapper_is_named_by_wasapi(self):
        mod, _ = pyaudio_module("Microsoft Sound Mapper - Input", "Microsoft Sound Mapper - Output",
                                devices=["Microphone (USB Audio CODEC )", "Speakers (Realtek(R) Audio)"],
                                wasapi=(0, 1))
        got = self.resolve(mod, name="windows")
        self.assertEqual((got["input"], got["output"]), ("Microphone (USB Audio CODEC )", "Speakers (Realtek(R) Audio)"))
        # With no WASAPI to ask, the mapper's own name: honest, if unhelpful.
        mod, _ = pyaudio_module("Microsoft Sound Mapper - Input", "Microsoft Sound Mapper - Output")
        self.assertEqual(self.resolve(mod, name="windows")["output"], "Microsoft Sound Mapper - Output")

    def test_without_portaudio_says_why(self):
        with mock.patch.dict(sys.modules, {"pyaudio": None}):      # None in sys.modules: ImportError
            got = audio.default_devices()
        self.assertEqual((got["input"], got["output"]), (None, None))
        self.assertIn("not installed", got["error"])

    def test_portaudio_failing_to_start_says_why(self):
        def broken():
            raise RuntimeError("PortAudio error -9999")
        got = self.resolve(types.SimpleNamespace(PyAudio=broken))
        self.assertIn("-9999", got["error"])


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        from helpers import make_radio
        from ohscore.ui.bridge import Bridge
        from ohsnb.ui.face import Qo100Face
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        self.radio = make_radio(self.tmp, audioOut="Speakers")
        self.bridge = Bridge(self.radio, face=Qo100Face())
        self.devs = [{"index": 0, "name": "Built-in Microphone", "inputs": 1, "outputs": 0, "rate": 48000.0},
                     {"index": 1, "name": "Speakers", "inputs": 0, "outputs": 2, "rate": 48000.0}]
        self.defaults = {"input": "Built-in Microphone", "output": "Speakers", "error": ""}
        self.patches = [mock.patch.object(audio, "list_devices", lambda: list(self.devs)),
                        mock.patch.object(audio, "default_devices", lambda: dict(self.defaults))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        for f in self.bridge.feeds.values():
            self.radio.unsubscribe(f)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dialog(self):
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui.settings import SettingsDialog
        d = SettingsDialog(self.bridge, Prefs(config.CONFIG))
        self.addCleanup(d.close)
        return d

    def test_system_default_says_which_device_it_is(self):
        d = self.dialog()
        self.assertEqual(d.audio_combos["audioIn"].itemText(0), "System default (Built-in Microphone)")
        self.assertEqual(d.audio_combos["audioOut"].itemText(0), "System default (Speakers)")
        self.assertEqual(d.audio_combos["audioOut2"].itemText(0), "None")     # not a default: nothing
        self.assertEqual(d.audio_combos["audioOut"].currentData(), "Speakers")   # the saved choice, kept

    def test_look_again_finds_a_new_default_and_keeps_the_choices(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from ohscore.ui.controls import Button
        d = self.dialog()
        d.audio_combos["audioIn"].setCurrentIndex(1)          # chosen in the dialog, not yet saved
        self.devs.append({"index": 2, "name": "USB Audio CODEC", "inputs": 1, "outputs": 2, "rate": 48000.0})
        self.defaults.update(input="USB Audio CODEC", output="USB Audio CODEC")
        look = next(b for b in d.findChildren(Button) if b.text == "Look again")
        QTest.mouseClick(look, Qt.MouseButton.LeftButton)
        self.assertEqual(d.audio_combos["audioIn"].itemText(0), "System default (USB Audio CODEC)")
        self.assertEqual(d.audio_combos["audioOut"].itemText(0), "System default (USB Audio CODEC)")
        self.assertEqual(d.audio_combos["audioIn"].currentData(), "Built-in Microphone")
        self.assertEqual(d.audio_combos["audioOut"].currentData(), "Speakers")
        self.assertGreaterEqual(d.audio_combos["audioOut"].findData("USB Audio CODEC"), 0)

    def test_no_device_of_a_kind(self):
        self.defaults.update(input=None)
        d = self.dialog()
        self.assertEqual(d.audio_combos["audioIn"].itemText(0), "System default (none found)")
        self.assertTrue(d.audio_none.isHidden())

    def test_without_portaudio_the_page_says_so(self):
        self.devs.clear()
        self.defaults.update(input=None, output=None, error="PortAudio (python3-pyaudio) is not installed")
        d = self.dialog()
        self.assertEqual(d.audio_combos["audioOut"].itemText(0), "System default")
        self.assertFalse(d.audio_none.isHidden())
        self.assertIn("python3-pyaudio", d.audio_none.text())
        # The saved speaker is still shown, as not connected, rather than lost.
        self.assertEqual(d.audio_combos["audioOut"].currentText(), "Speakers (not connected)")


if __name__ == "__main__":
    unittest.main()
