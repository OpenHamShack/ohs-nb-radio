"""Which USB Audio CODEC is the radio's (ohscore/rig/usbpair.py): by where
it sits on USB beside the CI-V port, never by name. A sysfs tree laid out
as Brian's 9700 is on shack (CI-V on 3-1.2.2/3-1.2.3, CODEC on 3-1.2.4)
with a second radio on another hub, and Windows' answer for Ray's PC, two
CODECs of which he had renamed the 9700's."""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import json
import os
import tempfile
import unittest
from pathlib import Path

from ohscore.rig import usbpair

ROOT = "devices/pci0000:00/0000:00:08.1/0000:e4:00.4/usb3"
NINE_7 = f"{ROOT}/3-1/3-1.2"            # the IC-9700's internal hub
OTHER = f"{ROOT}/3-2/3-2.1"             # a second radio's
LINUX = ["HD-Audio Generic: ALC269VC Analog (hw:1,0)", "USB Audio CODEC: - (hw:2,0)", "USB Audio CODEC: - (hw:3,0)"]
RAY_MME = ["Speakers / Headphones (Realtek ", "Speakers (2- USB AUDIO  CODEC)", "IC9700 Speakers (USB Audio CODE"]


def sysfs(root: Path, cards: dict, ttys: dict) -> None:
    """cards {n: device path}, ttys {name: device path} under root/devices."""
    for n, path in cards.items():
        (root / path).mkdir(parents=True, exist_ok=True)
        (root / "class" / "sound" / f"card{n}").mkdir(parents=True, exist_ok=True)
        os.symlink(root / path, root / "class" / "sound" / f"card{n}" / "device")
    for name, path in ttys.items():
        (root / path).mkdir(parents=True, exist_ok=True)
        (root / "class" / "tty" / name).mkdir(parents=True, exist_ok=True)
        os.symlink(root / path, root / "class" / "tty" / name / "device")


@unittest.skipIf(os.name == "nt", "sysfs symlinks")
class Linux(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        sysfs(self.root, {1: "devices/pci0000:00/0000:00:08.1/0000:e4:00.6",
                          2: f"{OTHER}/3-2.1.4/3-2.1.4:1.0", 3: f"{NINE_7}/3-1.2.4/3-1.2.4:1.0"},
              {"ttyUSB0": f"{OTHER}/3-2.1.1/3-2.1.1:1.0/ttyUSB0",
               "ttyUSB1": f"{NINE_7}/3-1.2.2/3-1.2.2:1.0/ttyUSB1"})

    def test_the_codec_beside_the_ci_v_port_is_the_radios(self):
        found = usbpair.linux_hubs("/dev/ttyUSB1", LINUX, sysfs=str(self.root))
        self.assertEqual(found["port"], "3-1.2")
        self.assertEqual(found["audio"][LINUX[2]], "3-1.2")
        self.assertEqual(found["audio"][LINUX[1]], "3-2.1")
        codecs = LINUX[1:]
        self.assertEqual(usbpair.pair(codecs, found["port"], found["audio"]), LINUX[2])
        # The other radio's port finds the other radio's CODEC.
        other = usbpair.linux_hubs("/dev/ttyUSB0", LINUX, sysfs=str(self.root))
        self.assertEqual(usbpair.pair(codecs, other["port"], other["audio"]), LINUX[1])

    def test_a_port_it_cannot_place_says_nothing(self):
        self.assertIsNone(usbpair.linux_hubs("/dev/ttyUSB9", LINUX, sysfs=str(self.root)))
        self.assertIsNone(usbpair.linux_hubs("socket://127.0.0.1:5000", LINUX, sysfs=str(self.root)))

    def test_two_codecs_on_one_hub_is_no_answer(self):
        self.assertIsNone(usbpair.pair(LINUX[1:], "3-1.2", {LINUX[1]: "3-1.2", LINUX[2]: "3-1.2"}))


def ray_nodes(parents=True):
    """Ray's PC as Windows' device tree shows it (the standalone diagnostic's
    fixture, tools/ic9700-diag): the 9700 behind its own hub (CP2102N COM4
    and COM6, a PCM2901 CODEC he renamed "IC9700 Speakers") and the FTDX10
    behind another (a CP2105, COM3/COM5, and another PCM2901), both on one
    external hub; and a Bluetooth COM port on the root hub beside a webcam."""
    def n(i, cls, name, parent, cont):
        return {"id": i, "cls": cls, "name": name, "parent": parent if parents else "", "container": cont}
    pc = usbpair.PC_CONTAINER
    return [
        n("USB\\VID_0451&PID_2046\\H97", "USB", "Generic USB Hub", "USB\\VID_05E3&PID_0610\\EXT", "{C97}"),
        n("USB\\VID_0424&PID_2512\\HFT", "USB", "Generic USB Hub", "USB\\VID_05E3&PID_0610\\EXT", "{CFT}"),
        n("USB\\VID_10C4&PID_EA60\\A", "Ports", "Silicon Labs CP210x USB to UART Bridge (COM4)",
          "USB\\VID_0451&PID_2046\\H97", "{C97}"),
        n("USB\\VID_10C4&PID_EA60\\B", "Ports", "Silicon Labs CP210x USB to UART Bridge (COM6)",
          "USB\\VID_0451&PID_2046\\H97", "{C97}"),
        n("USB\\VID_10C4&PID_EA70\\01AED7FB", "USB", "USB Composite Device", "USB\\VID_0424&PID_2512\\HFT", "{CFT}"),
        n("USB\\VID_10C4&PID_EA70&MI_00\\P0", "Ports",
          "Silicon Labs Dual CP2105 USB to UART Bridge: Enhanced COM Port (COM5)",
          "USB\\VID_10C4&PID_EA70\\01AED7FB", "{CFT}"),
        n("USB\\VID_08BB&PID_2901\\C97", "USB", "USB Composite Device", "USB\\VID_0451&PID_2046\\H97", "{C97}"),
        n("USB\\VID_08BB&PID_2901&MI_00\\M97", "MEDIA", "USB Audio CODEC", "USB\\VID_08BB&PID_2901\\C97", "{C97}"),
        n("USB\\VID_08BB&PID_2901\\CFT", "USB", "USB Composite Device", "USB\\VID_0424&PID_2512\\HFT", "{CFT}"),
        n("USB\\VID_08BB&PID_2901&MI_00\\MFT", "MEDIA", "USB AUDIO  CODEC", "USB\\VID_08BB&PID_2901\\CFT", "{CFT}"),
        n("SWD\\MMDEVAPI\\{0.0.0.00000000}.{E97}", "AudioEndpoint", "IC9700 Speakers (USB Audio CODEC)",
          "SWD\\MMDEVAPI\\MMDEVAPI", "{C97}"),
        n("SWD\\MMDEVAPI\\{0.0.0.00000000}.{EFT}", "AudioEndpoint", "Speakers (2- USB AUDIO  CODEC)",
          "SWD\\MMDEVAPI\\MMDEVAPI", "{CFT}"),
        n("SWD\\MMDEVAPI\\{0.0.1.00000000}.{M97}", "AudioEndpoint", "Microphone (USB Audio CODEC)",
          "SWD\\MMDEVAPI\\MMDEVAPI", "{C97}"),
        n("SWD\\MMDEVAPI\\{0.0.0.00000000}.{RTK}", "AudioEndpoint", "Speakers / Headphones (Realtek Audio)",
          "SWD\\MMDEVAPI\\MMDEVAPI", pc),
        # Straight into the computer: a Bluetooth COM port and a webcam
        # share the root hub, and no radio.
        n("BTHENUM\\{1101}\\BT", "Ports", "Standard Serial over Bluetooth link (COM9)", "USB\\VID_8087&PID_0026\\BT",
          pc),
        n("USB\\VID_8087&PID_0026\\BT", "USB", "Bluetooth", "USB\\ROOT_HUB30\\4&1", pc),
        n("USB\\VID_046D&PID_082D\\CAM", "USB", "HD Pro Webcam C920", "USB\\ROOT_HUB30\\4&1", pc),
        n("SWD\\MMDEVAPI\\{0.0.0.00000000}.{CAM}", "AudioEndpoint", "Speakers (HD Pro Webcam C920)",
          "USB\\VID_046D&PID_082D\\CAM", pc),
    ]


class Windows(unittest.TestCase):
    def test_rays_pc_the_renamed_one_on_the_9700s_own_hub(self):
        codecs = RAY_MME[1:]
        m = usbpair.windows_match(ray_nodes(), "COM4", codecs)
        self.assertEqual(m, {"IC9700 Speakers (USB Audio CODE": "hub"})     # MME cut it at 31 characters
        self.assertEqual(usbpair.pair(codecs, matched=m), "IC9700 Speakers (USB Audio CODE")
        # The FTDX10's port finds the FTDX10's CODEC.
        self.assertEqual(usbpair.windows_match(ray_nodes(), "COM5", codecs), {"Speakers (2- USB AUDIO  CODEC)": "hub"})
        # With no parent chains, Windows' container still decides.
        self.assertEqual(usbpair.windows_match(ray_nodes(parents=False), "COM4", codecs),
                         {"IC9700 Speakers (USB Audio CODE": "container"})

    def test_a_root_hub_or_the_computers_container_is_no_radio(self):
        self.assertEqual(usbpair.windows_match(ray_nodes(), "COM9", ["Speakers (HD Pro Webcam C920)"]), {})

    def test_powershell_output_and_failure(self):
        one = ray_nodes()[0]
        self.assertEqual(usbpair.windows_nodes(run=lambda _s: json.dumps(one)), [one])   # a single item, unwrapped
        self.assertEqual(usbpair.windows_nodes(run=lambda _s: ""), [])
        self.assertEqual(usbpair.windows_nodes(run=lambda _s: "not json"), [])
        self.assertEqual(usbpair.windows_match([], "COM4", RAY_MME), {})


if __name__ == "__main__":
    unittest.main()
