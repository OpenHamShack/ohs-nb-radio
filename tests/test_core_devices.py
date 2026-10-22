"""ohscore.devices.DeviceRegistry: the core supplies the real radios, each
app adds its own simulator, and make() behaves as ohsnb's old make_device."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore.devices import Device, DeviceError, DeviceRegistry
from ohsnb.devices import make_device


class Registry(unittest.TestCase):
    def test_an_app_registered_factory_gets_the_config_and_rate(self):
        seen = []

        class Fake(Device):
            kind = "fake"

        reg = DeviceRegistry()
        reg.register("fake", lambda cfg, fs: seen.append((cfg["x"], fs)) or Fake())
        dev = reg.make({"device": "fake", "sampleRate": 600_000, "x": 1})
        self.assertIsInstance(dev, Fake)
        self.assertEqual(seen, [(1, 600_000.0)])

    def test_unknown_device_is_a_sentence(self):
        with self.assertRaises(DeviceError) as cm:
            DeviceRegistry().make({"device": "nosuch"})
        self.assertIn("Unknown device 'nosuch'", str(cm.exception))

    def test_core_alone_has_no_simulator(self):
        # Which sim a program has is its app's choice, never the core's.
        with self.assertRaises(DeviceError):
            DeviceRegistry().make({"device": "sim"})

    def test_nb_offers_its_transponder_sim_by_default(self):
        dev = make_device({})
        self.assertEqual(dev.kind, "sim")
        self.assertEqual(dev.fs, 1_200_000.0)


if __name__ == "__main__":
    unittest.main()
