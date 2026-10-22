import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import tempfile
import unittest
from pathlib import Path

from ohsnb import config, state


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_gives_defaults(self):
        cfg = config.load(self.path)
        self.assertEqual(cfg["device"], "sim")
        self.assertEqual(cfg["memories"], [])

    def test_save_load_round_trip_and_no_temp_left(self):
        cfg = config.load(self.path)
        cfg["vfo"] = 10_489_612_000.0
        cfg["memories"] = [{"name": "net", "dl": 10_489_800_000.0, "mode": "usb"}]
        config.save(cfg, self.path)
        self.assertEqual(os.listdir(self.path.parent), ["config.json"])
        back = config.load(self.path)
        self.assertEqual(back["vfo"], 10_489_612_000.0)
        self.assertEqual(back["memories"][0]["name"], "net")

    def test_status_keys_never_persisted(self):
        cfg = config.load(self.path)
        cfg["keyed"] = True
        config.save(cfg, self.path)
        self.assertNotIn("keyed", json.loads(self.path.read_text()))

    def test_bad_values_fall_back_with_a_note(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"vfo": "lots", "txGain": -3, "txGainCeiling": -20, "nonsense": 1}))
        notes = []
        cfg = config.load(self.path, notes)
        self.assertEqual(cfg["vfo"], state.SPEC["vfo"]["default"])
        self.assertEqual(cfg["txGain"], -20)       # clamped to the ceiling
        self.assertNotIn("nonsense", cfg)
        self.assertTrue(notes)

    def test_unreadable_file_is_not_fatal(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        notes = []
        self.assertEqual(config.load(self.path, notes)["device"], "sim")
        self.assertTrue(notes)


class StateSpec(unittest.TestCase):
    def test_coerce_ranges_and_types(self):
        self.assertEqual(state.coerce("wideBins", "1024"), 1024)
        self.assertEqual(state.coerce("sampleRate", "600000"), 600000)
        with self.assertRaisesRegex(ValueError, "cannot be above"):
            state.coerce("txGain", 3)
        with self.assertRaisesRegex(ValueError, "one of"):
            state.coerce("mode", "fm")
        with self.assertRaises(ValueError):
            state.coerce("nope", 1)

    def test_every_key_described(self):
        for k, v in state.SPEC.items():
            self.assertIn(v["kind"], ("setting", "control", "status"), k)
            if v["kind"] != "status" and v["type"] in ("int", "float") and v["default"] is not None:
                self.assertEqual(state.coerce(k, v["default"]), v["default"], k)


if __name__ == "__main__":
    unittest.main()
