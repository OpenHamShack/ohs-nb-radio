"""Core pieces added for OpenHamShack HAM: a dict key's validate=, and a config
whose memories call their frequency something other than NB's "dl"."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import tempfile
import unittest
from pathlib import Path

from ohscore.config import AppId, Config
from ohscore.state import Registry, add_shared_keys


def only_numbers(v: dict) -> dict:
    if not all(isinstance(x, (int, float)) for x in v.values()):
        raise ValueError("stacks: numbers only")
    return {k: float(x) for k, x in v.items()}


class Hooks(unittest.TestCase):
    def setUp(self):
        self.reg = Registry(["usb", "fm"], set())
        add_shared_keys(self.reg)
        self.reg.add("stacks", "dict", {}, "control", validate=only_numbers)

    def test_dict_key_is_validated(self):
        self.assertEqual(self.reg.coerce("stacks", {"a": 1}), {"a": 1.0})
        with self.assertRaisesRegex(ValueError, "numbers only"):
            self.reg.coerce("stacks", {"a": "x"})
        # A key without validate= reads exactly as before the field existed.
        self.assertNotIn("validate", self.reg.spec["vfo"])

    def test_bad_dict_in_a_config_costs_that_key_only(self):
        cfg = Config(AppId("openhamshack-test", "OHSTEST"), self.reg, freq_key="rf")
        notes = []
        out = cfg.clean({"stacks": {"a": "x"}, "callsign": "GM4BRI"}, notes)
        self.assertEqual(out["stacks"], {})
        self.assertEqual(out["callsign"], "GM4BRI")
        self.assertTrue(notes)

    def test_memories_use_the_apps_frequency_key(self):
        cfg = Config(AppId("openhamshack-test", "OHSTEST"), self.reg, freq_key="rf")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"memories": [{"name": "GB3XX", "rf": 145_650_000, "mode": "fm"},
                                                  {"name": "old", "dl": 1.0}]}))
            out = cfg.load(p)
        self.assertEqual(out["memories"], [{"name": "GB3XX", "rf": 145_650_000.0, "mode": "fm"}])


if __name__ == "__main__":
    unittest.main()
