"""No default licence class (Brian, 05/10/2026; docs/ham/DESIGN-HAM.md,
"Decisions taken 05/10/2026"): a fresh install receives but refuses to
transmit until a class is chosen, says so wherever transmit is refused,
and a config written before the change keeps a class only where it can
be told apart from the old Foundation default."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ham_helpers import close, make_radio, pump
from ohscore import txguard
from ohsradio import config, guard


def refusal(st: dict) -> str:
    """What the shared dataset (ohscore/txguard.py, the guard both apps
    use since M3) says to this station about any transmission: the
    sentence txBlocked must carry."""
    return txguard.GUARD.check(txguard.profile(st), 145_500_000, 145_512_000, mode="fm").refused


class Guard(unittest.TestCase):
    def test_no_class_refuses_everywhere_with_the_reason(self):
        for f in (1_900_000, 14_200_000, 145_500_000, 433_500_000):
            v = guard.licence_check("", f, f + 2700, None)
            self.assertEqual(v.refused, guard.NO_CLASS, f)
        self.assertIn("No licence class chosen", guard.NO_CLASS)


class Engine(unittest.TestCase):
    def setUp(self):
        self.r = make_radio(licenceClass="")

    def tearDown(self):
        close(self.r)

    def test_a_fresh_radio_has_no_class(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = config.load(Path(tmp.name) / "config.json")
        self.assertEqual(cfg["licenceClass"], "")

    def test_receives_without_a_class_but_will_not_key(self):
        self.r.start()
        st = self.r.state()
        self.assertTrue(st["running"])
        self.assertEqual(st["txBlocked"], refusal({"callsign": self.r.st["callsign"]}))
        self.assertIn("No licence class chosen", st["txBlocked"])
        self.assertEqual(st["licenceInfo"]["level"], "refused")
        self.assertEqual(st["licenceInfo"]["class"], "")
        with self.assertRaisesRegex(ValueError, "No licence class chosen"):
            self.r.ptt(True)
        with self.assertRaisesRegex(ValueError, "No licence class chosen"):
            self.r.tune(True)
        self.assertFalse(self.r.state()["keyed"])
        self.assertEqual(self.r.dev.tx_written, 0)

    def test_receiving_produces_spectrum_without_a_class(self):
        wide = self.r.subscribe("wide", 256)
        self.r.start()
        lines = []
        pump(self.r, 5.0, until=lambda: bool(lines.extend(wide.drain()) or lines))
        self.assertTrue(lines)

    def test_choosing_a_class_unlocks_transmit(self):
        self.r.start()
        self.r.set(authorise=True, licenceClass="full")
        self.assertEqual(self.r.state()["txBlocked"], "")
        self.r.ptt(True)
        self.assertTrue(self.r.state()["keyed"])
        self.r.ptt(False)
        pump(self.r, 2.0, until=lambda: not self.r.state()["keyed"])
        # And unsetting it locks transmit again.
        self.r.set(authorise=True, licenceClass="")
        self.assertIn("No licence class chosen", self.r.state()["txBlocked"])


class StationCountry(unittest.TestCase):
    """The licence and plan follow the station's country (08/10/2026)."""

    def test_a_uk_station_keys_under_ofcom_on_the_rsgb_plan(self):
        r = make_radio(licenceClass="full")
        self.addCleanup(close, r)
        r.start()
        st = r.state()
        self.assertEqual((st["station"]["regime"], st["planInUse"]), ("ofcom-2024", "rsgb-2026"))
        self.assertEqual(st["txBlocked"], "")

    def test_a_country_with_no_licence_written_receives_but_will_not_key(self):
        r = make_radio(callsign="ZS1ABC", licenceClass="full")
        self.addCleanup(close, r)
        r.start()
        st = r.state()
        self.assertEqual(st["station"]["entity"], "South Africa")
        self.assertEqual(st["txBlocked"], refusal({"callsign": "ZS1ABC", "licenceClass": "full"}))
        self.assertIn("No licence for South Africa", st["txBlocked"])
        self.assertEqual(st["planInUse"], "iaru-r1")
        with self.assertRaisesRegex(ValueError, "No licence for South Africa"):
            r.ptt(True)
        self.assertEqual(r.dev.tx_written, 0)

    def test_moving_the_station_while_keyed_unkeys(self):
        r = make_radio(licenceClass="full", mode="usb", vfo=14_200_000.0)
        self.addCleanup(close, r)
        r.start()
        r.ptt(True)
        pump(r, 2.0, until=lambda: r.state()["keyed"])
        self.assertTrue(r.state()["keyed"])
        r.set(authorise=True, stationCountry="ZS")
        pump(r, 2.0, until=lambda: not r.state()["keyed"])
        self.assertFalse(r.state()["keyed"])


class Migration(unittest.TestCase):
    """A file written before the change said "foundation" whether or not
    anyone chose it (every save writes every key)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf = Path(self.tmp.name) / "config.json"
        self.ui = Path(self.tmp.name) / "ui.json"
        env = mock.patch.dict(os.environ, {"OHS_RADIO_UI_CONF": str(self.ui)})
        env.start()
        self.addCleanup(env.stop)

    def old_file(self, cls, ack=None):
        self.conf.write_text(json.dumps({"licenceClass": cls, "callsign": "GM4BRI", "memories": []}))
        if ack is not None:
            self.ui.write_text(json.dumps({"welcomed": True, "licenceAck": ack}))

    def test_unconfirmed_foundation_becomes_unset_with_a_note(self):
        for ack in (None, False):
            self.old_file("foundation", ack)
            notes = []
            cfg = config.load(self.conf, notes)
            self.assertEqual(cfg["licenceClass"], "", ack)
            self.assertEqual(cfg["callsign"], "GM4BRI")
            self.assertTrue(any("old default" in n for n in notes), notes)

    def test_foundation_confirmed_by_the_licence_box_is_kept(self):
        self.old_file("foundation", True)
        notes = []
        self.assertEqual(config.load(self.conf, notes)["licenceClass"], "foundation")
        self.assertEqual(notes, [])

    def test_intermediate_and_full_were_always_chosen(self):
        for cls in ("intermediate", "full"):
            self.old_file(cls)
            self.assertEqual(config.load(self.conf)["licenceClass"], cls)

    def test_a_file_written_after_the_change_is_taken_as_it_is(self):
        cfg = config.load(self.conf)
        cfg["licenceClass"] = "foundation"
        config.save(cfg, self.conf)
        self.assertEqual(json.loads(self.conf.read_text())["configVersion"], config.VERSION)
        # Chosen in Settings without ticking the licence box: still chosen.
        self.ui.write_text(json.dumps({"licenceAck": False}))
        self.assertEqual(config.load(self.conf)["licenceClass"], "foundation")

    def test_a_dict_handed_to_the_engine_is_never_migrated(self):
        r = make_radio(licenceClass="foundation")
        self.addCleanup(close, r)
        self.assertEqual(r.state()["licenceClass"], "foundation")

    def version2_file(self, call, licence="ofcom-2024", plan="rsgb-2026"):
        self.conf.write_text(json.dumps({"configVersion": 2, "licenceClass": "full", "callsign": call,
                                         "licence": licence, "plan": plan, "memories": []}))

    def test_a_uk_station_follows_its_country_from_version_3(self):
        # Every version-2 save wrote Ofcom and the RSGB plan, the only
        # choices: for a UK call "auto" gives exactly those.
        self.version2_file("GM4BRI")
        notes = []
        cfg = config.load(self.conf, notes)
        self.assertEqual((cfg["licence"], cfg["plan"], cfg["licenceClass"]), ("auto", "auto", "full"))
        self.assertEqual(notes, [])

    def test_anyone_else_keeps_what_they_keyed_under(self):
        for call in ("", "EA8/GM4BRI", "W1AW"):
            self.version2_file(call)
            notes = []
            cfg = config.load(self.conf, notes)
            self.assertEqual((cfg["licence"], cfg["plan"]), ("ofcom-2024", "rsgb-2026"), call)
            self.assertTrue(any("choose 'auto'" in n for n in notes), (call, notes))

    def test_nb_writes_no_version(self):
        from ohsnb import config as nb_config
        p = Path(self.tmp.name) / "nb.json"
        nb_config.save(nb_config.load(p), p)
        self.assertNotIn("configVersion", json.loads(p.read_text()))


if __name__ == "__main__":
    unittest.main()
