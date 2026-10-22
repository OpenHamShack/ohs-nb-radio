"""One rule for what a callsign is (ohscore/callsign.py), shared by every
place that checks one: Settings, PSKReporter, the FT8 decoder's jt9
arguments, QRZ links, the logbook. Each used to have its own, and each was
written for a UK call; an operator signing EA8/GM4BRI/P or VE3/W1AW must
be accepted by all of them alike."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest

from ohscore import callsign, pskreporter
from ohscore.logbook import Logbook
from ohscore.modes import ft8

INTERNATIONAL = ["GM4BRI", "G4ABC", "M0XYZ", "2E0ABC", "MM7ABC", "W1AW", "K1A", "VE3ABC", "VK2ABC", "ZL1ABC",
                 "JA1ABC", "9A1AA", "4U1ITU", "3DA0AB", "GB100RSGB", "OH2BH", "LA1ABC", "DL1ABC", "F5ABC"]
PORTABLE = ["GM4BRI/P", "GM4BRI/M", "GM4BRI/MM", "GM4BRI/AM", "EA8/GM4BRI", "EA8/GM4BRI/P", "VE3/W1AW",
            "W1AW/4", "G4ABC/EA8", "KH6/W1AW", "VP2E/K1ABC", "G4ABC/P/QRP", "pj4/k1abc"]
NOT_CALLS = ["", "   ", "TEST", "CQ", "EA8", "IO86", "G4 ABC", "G4ABC'", "/G4ABC", "G4ABC/", "G4ABC//P",
             "A/B/C/D/E", "GM4BRI/P/QRP/X/Y", "ABCDEFGHIJ1K"]


class Shape(unittest.TestCase):
    def test_home_and_portable_calls_are_calls(self):
        for c in INTERNATIONAL + PORTABLE:
            self.assertTrue(callsign.valid(c), c)

    def test_what_is_not_a_call(self):
        for c in NOT_CALLS:
            self.assertFalse(callsign.valid(c), c)

    def test_parts(self):
        p = callsign.parts("ea8/gm4bri/p")
        self.assertEqual((p.prefix, p.home, p.suffixes), ("EA8", "GM4BRI", ("P",)))
        self.assertEqual(callsign.parts("VE3/W1AW").home, "W1AW")
        self.assertEqual(callsign.parts("VP2E/K1ABC").prefix, "VP2E")
        self.assertEqual(callsign.parts("W1AW/4").suffixes, ("4",))
        self.assertEqual(callsign.home("EA8/GM4BRI/P"), "GM4BRI")
        self.assertEqual(callsign.home("<G4ABC>"), "G4ABC")

    def test_abroad_means_a_place_not_a_manner(self):
        for c in ("EA8/GM4BRI", "VE3/W1AW", "W1AW/4", "G4ABC/EA8"):
            self.assertTrue(callsign.is_portable_abroad(c), c)
        for c in ("GM4BRI", "GM4BRI/P", "GM4BRI/MM", "G4ABC/P/QRP"):
            self.assertFalse(callsign.is_portable_abroad(c), c)


class EveryPlaceAgrees(unittest.TestCase):
    def test_pskreporter(self):
        for c in INTERNATIONAL + PORTABLE:
            self.assertTrue(pskreporter.valid_call(c), c)
        for c in NOT_CALLS:
            self.assertFalse(pskreporter.valid_call(c), c)

    def test_jt9_arguments(self):
        for c in INTERNATIONAL + PORTABLE:
            self.assertEqual(ft8._jt9_call(c), f"'{c.upper()}'", c)
        for c in NOT_CALLS:
            self.assertEqual(ft8._jt9_call(c), "b", c)
        # jt9's call fields are 12 characters: a longer valid call cannot go whole.
        self.assertTrue(callsign.valid("VP2E/GB100RSGB"))
        self.assertEqual(ft8._jt9_call("VP2E/GB100RSGB"), "b")

    def test_qrz_link(self):
        from ohscore.ui.logbook import qrz_call
        self.assertEqual(qrz_call("EA8/GM4BRI/P"), "GM4BRI")
        self.assertEqual(qrz_call("VE3/W1AW"), "W1AW")
        self.assertEqual(qrz_call("G4ABC/MM"), "G4ABC")

    def test_logbook_keeps_the_whole_portable_call(self):
        with tempfile.TemporaryDirectory() as d:
            lb = Logbook(d, freq_key="rf", adif_fields=lambda r: ([], []), title="t", program_id="T")
            rec = lb.add("ea8/gm4bri/p", 14_074_000.0, "ft8")
            self.assertEqual(rec["call"], "EA8/GM4BRI/P")


if __name__ == "__main__":
    unittest.main()
