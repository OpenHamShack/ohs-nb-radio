"""The antenna setting end to end on the engine (OpenHamShack Radio): a
fake SoapySDR-shaped device with three inputs, switched live while the
radio runs - what tests/test_soapy.py checks against SoapySDRPlay3's own
shape, this checks against Engine.set() and _configure_rx, the path a
Settings save or api/set actually takes."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import time
import unittest

import numpy as np

from ohscore.devices.base import Device, DeviceError
from ohsradio.radio import Radio

ANTENNAS = ("Antenna A", "Antenna B", "Antenna C")


class FakeAntennaDevice(Device):
    """Just enough of the Device interface to run an Engine: a receiver
    with three named inputs and a live setAntenna, as SoapySDRPlay3's does
    (tests/test_soapy.py covers the real SoapyDevice against that shape;
    this is the engine side of the same contract)."""

    kind = "fakeant"
    can_tx = False
    fs = 1_200_000.0

    def __init__(self, initial: str = ""):
        self.antenna = initial or ANTENNAS[0]
        self.calls: list[str] = []
        self.opened = 0
        self.closed = 0

    @property
    def antennas(self) -> list[str]:
        return list(ANTENNAS)

    def open(self) -> None:
        self.opened += 1

    def close(self) -> None:
        self.closed += 1

    def set_rx_if(self, hz: float) -> None:
        pass

    def read(self, n: int) -> np.ndarray:
        time.sleep(n / self.fs)        # paced, so the rx thread does not spin
        return np.zeros(n, np.complex64)

    def set_antenna(self, name: str) -> None:
        self.calls.append(name)
        if name and name not in ANTENNAS:
            raise DeviceError(f"This SDR has no antenna input called {name!r}")
        if name:
            self.antenna = name

    def status(self) -> dict:
        return {"kind": self.kind, "antenna": self.antenna, "antennas": self.antennas, "tx": "receive only"}


class AntennaLive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dev = FakeAntennaDevice(initial="Antenna A")
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "callsign": "GM4BRI",
               "licenceClass": "foundation", "soapyAntenna": "Antenna A"}
        self.radio = Radio(cfg, persist=False, data_dir=self.tmp.name, device=self.dev)
        self.addCleanup(self.radio.stop)
        self.radio.start()

    def _wait_for(self, pred, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return True
            self.radio.heartbeat()
            time.sleep(0.01)
        return pred()

    def test_restart_flag_is_off_so_a_settings_save_never_reopens_for_it(self):
        self.assertFalse(self.radio.STATE.spec["soapyAntenna"]["restart"])

    def test_the_drop_down_choice_appears_under_deviceStatus(self):
        # deviceStatus is filled by the supervisor loop (every 0.1 s, not
        # at start()), so this waits for it rather than racing it.
        self.assertTrue(self._wait_for(lambda: self.radio.state().get("deviceStatus", {}).get("antenna")))
        st = self.radio.state()
        self.assertEqual(st["deviceStatus"]["antenna"], "Antenna A")
        self.assertEqual(st["deviceStatus"]["antennas"], ["Antenna A", "Antenna B", "Antenna C"])

    def test_changing_the_setting_switches_live_with_no_reopen(self):
        before_opens, before_closes = self.dev.opened, self.dev.closed
        self.radio.set(soapyAntenna="Antenna C")
        self.assertTrue(self._wait_for(lambda: self.dev.antenna == "Antenna C"))
        self.assertIn("Antenna C", self.dev.calls)
        self.assertEqual(self.dev.opened, before_opens)      # never reopened
        self.assertEqual(self.dev.closed, before_closes)
        self.assertTrue(self._wait_for(lambda: self.radio.state().get("deviceStatus", {}).get("antenna") == "Antenna C"))

    def test_an_unknown_input_is_refused_by_the_device_and_toasted_not_crashed(self):
        self.radio.set(soapyAntenna="Antenna Z")
        self.assertTrue(self._wait_for(lambda: "Antenna Z" in self.dev.calls))
        # Refused by the device: the antenna stays where it was, and the
        # radio is still running (no crash, no silent success either).
        self.assertEqual(self.dev.antenna, "Antenna A")
        self.assertTrue(self.radio.state()["running"])

    def test_driver_default_is_accepted_and_leaves_the_current_input(self):
        self.radio.set(soapyAntenna="Antenna B")
        self.assertTrue(self._wait_for(lambda: self.dev.antenna == "Antenna B"))
        self.radio.set(soapyAntenna="")
        self.assertTrue(self._wait_for(lambda: "" in self.dev.calls))
        self.assertEqual(self.dev.antenna, "Antenna B")      # "" means "don't touch it"


if __name__ == "__main__":
    unittest.main()
