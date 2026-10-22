"""The shared logbook and station profile (ohscore/station.py,
ohscore/logbook.py over ohs-libs shack_client): BETA-PLAN architecture
change 2, offline first, one log per station, a controller joined when
there is one and left without losing anything.

The controller here is shack_client's reference controller, served over
real HTTP on loopback: the same merge and sequence code the Dock360
edition mounts, so pairing, a first exchange, an edit coming back and an
unpair are the real protocol, not a mock."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import ham_helpers
import helpers
from ohscore import shacklibs


def nb(tmp, **over):
    return helpers.make_radio(tmp, **over)


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        lines = [{"call": "G4XYZ", "t": 1_790_000_000.0, "dl": 10_489_701_000.0, "mode": "usb", "rstSent": "59"},
                 {"call": "DL1ABC", "t": 1_790_000_100.0, "dl": 10_489_540_000.0, "mode": "ft8"}]
        (self.dir / "log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines) + "not json\n")

    def test_old_log_moves_in_once_and_is_kept(self):
        r = nb(self.tmp.name)
        e = r.log_entries()
        self.assertEqual([(x["call"], x["dl"], x["mode"]) for x in e],
                         [("G4XYZ", 10_489_701_000.0, "usb"), ("DL1ABC", 10_489_540_000.0, "ft8")])
        self.assertEqual(e[0]["rstSent"], "59")
        self.assertTrue(all(len(x["uuid"]) == 36 for x in e))
        self.assertFalse((self.dir / "log.jsonl").exists())
        self.assertTrue((self.dir / "log.jsonl.migrated").exists())
        # The stored contact is a QO-100 contact in ADIF terms.
        q = r.station.logbook.get(e[0]["uuid"])
        self.assertEqual((q.fields["band"], q.fields["band_rx"], q.fields["prop_mode"], q.fields["sat_name"],
                          q.fields["freq_hz"], q.fields["freq_rx_hz"]),
                         ("13cm", "3cm", "SAT", "QO-100", 2_400_201_000, 10_489_701_000))
        r.station.close()

    def test_a_migration_run_again_adds_nothing(self):
        r = nb(self.tmp.name)
        self.assertEqual(len(r.log_entries()), 2)
        (self.dir / "log.jsonl.migrated").rename(self.dir / "log.jsonl")
        r.station.close()
        r2 = nb(self.tmp.name)
        self.assertEqual(len(r2.log_entries()), 2)
        r2.station.close()


class OneLogForBothApps(unittest.TestCase):
    """SYNC.md 2.1: QO-100 NB and Radio on one computer keep one log."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"SHACK_STATION_DB": str(Path(self.tmp.name) / "station.db")})
        env.start()
        self.addCleanup(env.stop)
        self.nb = nb(self.tmp.name)
        self.ham = ham_helpers.make_radio()
        self.addCleanup(ham_helpers.close, self.ham)

    def tearDown(self):
        self.nb.station.close()
        self.ham.station.close()

    def test_a_contact_logged_in_radio_is_in_nb(self):
        self.ham.log_qso("m0abc", rf=144_300_000.0, mode="usb", t=1_790_000_000)
        e = self.nb.log_entries()
        self.assertEqual([x["call"] for x in e], ["M0ABC"])
        # NB shows its downlink key; a terrestrial contact has only freq_hz.
        self.assertEqual(e[0]["dl"], 144_300_000.0)

    def test_nb_editing_radios_contact_leaves_it_terrestrial(self):
        self.ham.log_qso("m0abc", rf=144_300_000.0, mode="usb", t=1_790_000_000)
        self.nb.edit_qso(0, rstRcvd="57")
        q = self.ham.station.logbook.query()[0]
        self.assertEqual(q.fields["rst_rcvd"], "57")
        self.assertEqual(q.fields["band"], "2m")
        self.assertNotIn("sat_name", q.fields)
        self.assertEqual(q.origin["app"], "shack-radio")

    def test_adif_names_the_app_and_carries_the_uuid(self):
        rec = self.nb.log_qso("dl1abc", dl=10_489_540_000.0, mode="js8", t=1_790_000_000)
        text = self.nb.export_adif(Path(self.tmp.name) / "out.adi").read_text()
        self.assertIn("<PROGRAMID:22>OpenHamShack QO-100 NB", text)
        self.assertIn(f"<APP_SHACK_UUID:36>{rec['uuid']}", text)
        self.assertIn("<MODE:4>MFSK", text)
        self.assertIn("<SUBMODE:3>JS8", text)
        text = self.ham.export_adif(Path(self.tmp.name) / "ham.adi").read_text()
        self.assertIn("<PROGRAMID:18>OpenHamShack Radio", text)
        # An import of our own export is the same contact, not a copy.
        report = self.ham.logbook.import_adif(text)
        self.assertEqual((report["added"], len(report["duplicates"])), (0, 1))


class Profile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.r = ham_helpers.make_radio(locator="IO75RL")
        self.addCleanup(ham_helpers.close, self.r)
        self.link = self.r.station_link
        self.addCleanup(self.r.station.close)

    def test_settings_fill_an_empty_profile(self):
        self.link.adopt()
        p = self.r.station.profile.get()
        self.assertEqual((p["callsign"], p["locator"], p["licence"]["class"]), ("GM4BRI", "IO75RL", "foundation"))

    def test_a_profile_changed_elsewhere_reaches_the_settings(self):
        self.link.adopt()
        self.r.station.profile.update({"licence": {"regime": "auto", "class": "full", "custom": []},
                                       "locator": "IO86AA"})
        self.link.pull()
        self.assertEqual((self.r.st["licenceClass"], self.r.st["locator"]), ("full", "IO86AA"))
        # ... and the guard follows at once: Full's 2 m limit.
        self.r.set(vfo=145_500_000.0, mode="fm")
        self.r.start()
        ham_helpers.pump(self.r, 0.2)
        self.assertEqual(self.r.state()["licenceInfo"]["limitW"], 1000)

    def test_a_value_this_app_cannot_hold_is_left_out(self):
        self.link.adopt()
        self.r.station.profile.update({"licence": {"regime": "auto", "class": "no_such_class", "custom": []}})
        self.link.pull()
        self.assertEqual(self.r.st["licenceClass"], "foundation")

    def test_operator_changes_go_into_the_profile(self):
        self.link.adopt()
        self.r.persist = True                  # push runs for the operator's program only
        self.r._save = lambda force=False: None
        self.r.set(locator="JO62AB")
        self.assertEqual(self.r.station.profile.get()["locator"], "JO62AB")


class Controller(unittest.TestCase):
    """Pair, share the log both ways, unpair and keep the local copy."""

    def setUp(self):
        sc = shacklibs.client()
        from shack_client.testing import ReferenceController
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctl = ReferenceController(Path(self.tmp.name) / "controller.db", name="GM4BRI")
        self.url = self.ctl.serve()
        self.addCleanup(self.ctl.close)
        self.sc = sc
        self.r = nb(str(Path(self.tmp.name) / "nb"), callsign="GM4BRI")
        self.link = self.r.station_link
        self.addCleanup(self.r.station.close)

    def wait(self, cond, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def test_pair_share_both_ways_and_unpair(self):
        mine = self.r.log_qso("g4xyz", dl=10_489_701_000.0, mode="usb", t=1_790_000_000)
        result = self.link.pair(self.url, "brian", "pw", device_name="test laptop")
        self.assertIsInstance(result, self.sc.Pairing)
        self.assertEqual(self.link.pairing()["name"], "GM4BRI")
        self.assertIn(mine["uuid"], self.ctl.records())
        self.assertEqual(self.ctl.records()[mine["uuid"]]["fields"]["sat_name"], "QO-100")
        # A contact another device logged on the controller comes back.
        self.ctl.sync.edit("logbook", "0192aaaa-0000-7000-8000-000000000001", "create",
                           {"call": "EA8XYZ", "start": "2026-10-09T10:00:00Z", "freq_hz": 2_400_300_000,
                            "freq_rx_hz": 10_489_800_000, "mode": "SSB", "submode": "USB"},
                           {"app": "remote", "device": "dev_X", "user": "brian"})
        self.link.sync_now()
        self.assertTrue(self.wait(lambda: any(e["call"] == "EA8XYZ" for e in self.r.log_entries())))
        self.assertEqual(self.link.status()["state"], "idle")
        self.link.unpair()
        self.assertEqual(self.link.status()["state"], "unpaired")
        self.assertIsNone(self.link.pairing())
        self.assertEqual(sorted(e["call"] for e in self.r.log_entries()), ["EA8XYZ", "G4XYZ"])
        # And it keeps logging, standalone.
        self.r.log_qso("m0abc", dl=10_489_702_000.0, mode="usb")
        self.assertEqual(len(self.r.log_entries()), 3)

    def test_wrong_password_is_a_sentence(self):
        with self.assertRaises(self.sc.PairingError) as cm:
            self.link.pair(self.url, "brian", "nope")
        self.assertTrue(str(cm.exception))
        self.assertEqual(self.link.status()["state"], "unpaired")

    def test_a_controller_that_is_not_there_is_offline_not_a_crash(self):
        self.ctl.close()
        with self.assertRaises(self.sc.Offline):
            self.link.pair(self.url, "brian", "pw")
        self.r.log_qso("m0abc", dl=10_489_702_000.0, mode="usb")
        self.assertEqual(len(self.r.log_entries()), 1)


if __name__ == "__main__":
    unittest.main()
