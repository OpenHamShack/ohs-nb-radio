"""ohscore.config is per app: two apps' files, folders and environment
variables never meet. (NB's own folders and variables, unchanged by the
core split, are tested in test_host.py's Folders.)"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ohscore import host
from ohscore.config import AppId, Config
from ohscore.state import Registry, add_shared_keys
from ohsnb import config as nb_config
from systems import system


def other_app():
    reg = Registry(["usb", "fm"], set())
    add_shared_keys(reg)
    return Config(AppId(name="openhamshack-other", env="LBOTHER"), reg)


class PerApp(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ)
        self.env.start()
        for k in ("OHS_NB_CONF", "OHS_NB_DATA", "OHSNB_CONF", "OHSNB_DATA", "LBOTHER_CONF", "LBOTHER_DATA"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()

    def test_folders_are_named_after_the_app(self):
        other = other_app()
        for win in (False, True):
            with system("windows" if win else "linux"):
                self.assertEqual(other.conf_path().parent.name, "openhamshack-other")
                self.assertNotEqual(other.conf_path(), nb_config.conf_path())
                self.assertNotEqual(other.data_dir(), nb_config.data_dir())

    def test_each_app_reads_only_its_own_environment(self):
        os.environ["OHS_NB_CONF"] = "/nb/c.json"
        self.assertNotEqual(other_app().conf_path(), Path("/nb/c.json"))
        os.environ["LBOTHER_CONF"] = "/other/c.json"
        self.assertEqual(other_app().conf_path(), Path("/other/c.json"))
        self.assertEqual(nb_config.conf_path(), Path("/nb/c.json"))

    def test_an_app_without_repair_rules_round_trips(self):
        other = other_app()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            cfg = other.load(p)
            cfg["mode"] = "fm"
            other.save(cfg, p)
            self.assertEqual(other.load(p)["mode"], "fm")
            # NB's QO-100 keys are not this app's and are not written.
            self.assertNotIn("lnbLo", other.load(p))


if __name__ == "__main__":
    unittest.main()
