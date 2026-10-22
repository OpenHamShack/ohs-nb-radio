"""ohscore.logbook and ohscore.memories with an app other than NB: the record's
frequency key and the ADIF fields are the app's. (NB's own log, memories
and ADIF are exercised through the Radio in test_radio.py.)"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest
from pathlib import Path

from ohscore.logbook import Logbook
from ohscore.memories import Memories


def terrestrial(r):
    return [("BAND", "2m"), ("FREQ", f"{r['rf'] / 1e6:.6f}")], []


class OtherApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Logbook(Path(self.tmp.name), freq_key="rf", adif_fields=terrestrial,
                           title="Other log export", program_id="Other")

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_use_the_apps_frequency_key(self):
        rec = self.log.add("m0abc", 144_300_000.0, "usb", t=1.0)
        uid = rec.pop("uuid")
        self.assertEqual(rec, {"call": "M0ABC", "t": 1.0, "rf": 144_300_000.0, "mode": "usb"})
        self.assertEqual(self.log.entries()[0]["uuid"], uid)
        self.log.edit(0, rf=144_301_000.0)
        self.assertEqual(self.log.entries()[0]["rf"], 144_301_000.0)

    def test_adif_carries_the_apps_fields_and_no_satellite(self):
        self.log.add("M0ABC", 144_300_000.0, "usb", t=1.0)
        text = self.log.export_adif(callsign="GM4BRI").read_text()
        self.assertIn("<PROGRAMID:5>Other", text)
        self.assertIn("<BAND:2>2m <FREQ:10>144.300000 <MODE:3>SSB <SUBMODE:3>USB", text)
        self.assertNotIn("SAT_NAME", text)

    def test_memories_store_the_apps_frequency_key(self):
        def coerce(key, v):
            return float(v) if key == "vfo" else v

        mem = Memories([{"name": "calling", "rf": 144_300_000.0, "mode": "usb"}], [], coerce, freq_key="rf")
        mem.store(mem.make("net", 145_500_000.0, "fm"))
        self.assertEqual([m["name"] for m in mem.listing()], ["calling", "net"])
        self.assertEqual(mem.find("net")["rf"], 145_500_000.0)
        self.assertTrue(mem.find("calling")["builtin"])


if __name__ == "__main__":
    unittest.main()
