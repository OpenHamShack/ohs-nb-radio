"""The CW and keyboard macros' fields (ohscore/ui/prefs.py): what a CW
memory sends, and that one whose field is empty is not sent at all."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore.ui.prefs import expand_macro, macro_missing


class Fields(unittest.TestCase):
    def test_every_field_is_filled(self):
        self.assertEqual(expand_macro("{DXCALL} DE {MYCALL} UR {RST} QTH {LOC} BK", "GM4BRI", "DL1ABC", "579",
                                      "IO86ha"),
                         "DL1ABC DE GM4BRI UR 579 QTH IO86ha BK")
        self.assertEqual(expand_macro("{CALL} {DXCALL}", "GM4BRI", "DL1ABC"), "DL1ABC DL1ABC")

    def test_a_macro_missing_a_field_says_which(self):
        self.assertEqual(macro_missing("CQ DE {MYCALL} K", "GM4BRI"), "")
        self.assertIn("their call", macro_missing("{DXCALL} DE {MYCALL}", "GM4BRI", ""))
        self.assertIn("their call", macro_missing("{CALL} TU", "GM4BRI", ""))
        self.assertIn("callsign", macro_missing("CQ DE {MYCALL}", ""))
        self.assertIn("locator", macro_missing("LOC {LOC}", "GM4BRI", "", ""))
        self.assertEqual(macro_missing("{DXCALL} {LOC}", "GM4BRI", "DL1ABC", "IO86"), "")


if __name__ == "__main__":
    unittest.main()
