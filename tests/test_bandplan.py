import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohsnb import bandplan as bp


class Conversions(unittest.TestCase):
    def test_uplink_downlink_round_trip(self):
        self.assertEqual(bp.ul(10_489_750_000.0), 2_400_250_000.0)
        self.assertEqual(bp.dl(2_400_000_000.0), 10_489_500_000.0)
        for f in (10_489_500_000.0, 10_489_612_345.5, 10_490_000_000.0):
            self.assertEqual(bp.dl(bp.ul(f)), f)

    def test_segment_lookup(self):
        self.assertEqual(bp.segment_at(10_489_520_000.0)["label"], "CW only")
        self.assertFalse(bp.segment_at(10_489_750_000.0)["tx"])
        self.assertTrue(bp.segment_at(10_489_860_000.0)["tx"])
        self.assertIsNone(bp.segment_at(10_489_400_000.0))


class Guard(unittest.TestCase):
    def test_ssb_in_ssb_segment_allowed(self):
        self.assertEqual(bp.tx_blocked(10_489_700_300.0, 10_489_702_700.0, "usb"), "")

    def test_beacon_segments_refused(self):
        self.assertIn("beacon", bp.tx_blocked(10_489_746_000.0, 10_489_748_400.0, "usb"))
        self.assertIn("beacon", bp.tx_blocked(10_489_502_000.0, 10_489_502_100.0, "cw"))
        self.assertIn("beacon", bp.tx_blocked(10_489_995_000.0, 10_489_996_000.0, "ft8"))

    def test_edge_straddling_a_beacon_guard_refused(self):
        # Dialled below the guard, but the speech reaches into it.
        self.assertIn("middle beacon", bp.tx_blocked(10_489_743_000.0, 10_489_745_400.0, "usb"))

    def test_outside_transponder_refused(self):
        self.assertIn("outside", bp.tx_blocked(10_489_400_000.0, 10_489_402_400.0, "usb"))

    def test_too_wide_refused(self):
        self.assertIn("2.7 kHz", bp.tx_blocked(10_489_700_000.0, 10_489_703_000.0, "usb"))

    def test_mode_rules(self):
        self.assertIn("SSB voice is not allowed", bp.tx_blocked(10_489_520_300.0, 10_489_522_700.0, "usb"))
        self.assertEqual(bp.tx_blocked(10_489_520_700.0, 10_489_520_700.0, "cw"), "")
        self.assertEqual(bp.tx_blocked(10_489_541_000.0, 10_489_541_050.0, "ft8"), "")
        self.assertIn("500 Hz", bp.tx_blocked(10_489_541_000.0, 10_489_542_000.0, "freedv"))
        self.assertIn("Digital modes", bp.tx_blocked(10_489_700_000.0, 10_489_700_050.0, "ft8"))
        self.assertEqual(bp.tx_blocked(10_489_870_300.0, 10_489_872_700.0, "usb"), "")

    def test_presets_are_in_band(self):
        for p in bp.PRESETS:
            self.assertTrue(bp.DL_LO - 1000 <= p["dl"] <= bp.DL_HI, p)


if __name__ == "__main__":
    unittest.main()
