"""The shared converter model (ohscore/converters.py): the maths both ways
for all four type/inversion combinations, checked against SDR Console's
own examples; storage; the preset packs."""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import unittest

from ohscore import converters as cv
from ohscore.converters import DOWN, RX, RXTX, UP, Converter
from ohscore.state import Registry, add_shared_keys

MHZ = 1e6


class Maths(unittest.TestCase):
    # SDR Console's help text: a 144 MHz transverter feeding an HF SDR puts
    # 144-146 MHz out as 28-30 MHz, 116 MHz lower...
    def test_down_not_inverted_is_116_lower(self):
        c = Converter("144 MHz (28 MHz IF)", DOWN, RXTX, 116 * MHZ, 116 * MHZ)
        self.assertEqual(c.radio_range(144 * MHZ, 146 * MHZ), (28 * MHZ, 30 * MHZ))
        self.assertEqual(c.air(28.2 * MHZ), 144.2 * MHZ)
        self.assertEqual(c.example(144 * MHZ, 146 * MHZ), "144-146 MHz on air appears at 28-30 MHz on the radio")
        self.assertEqual(c.check(144 * MHZ, 146 * MHZ), "")

    # ...and an HF upconverter feeding a VHF SDR puts 1-30 MHz in as
    # 151-180 MHz, 150 MHz higher.
    def test_up_not_inverted_is_150_higher(self):
        c = Converter("HF upconverter", UP, RX, 150 * MHZ, 150 * MHZ)
        self.assertEqual(c.radio_range(1 * MHZ, 30 * MHZ), (151 * MHZ, 180 * MHZ))
        self.assertEqual(c.air(164.2 * MHZ), 14.2 * MHZ)
        self.assertEqual(c.check(1 * MHZ, 30 * MHZ), "")

    def test_sdr_console_transverter_examples(self):
        for title, off, air, radio in [("1296 MHz (28 MHz IF)", 1268, 1296.2, 28.2),
                                       ("1296 MHz (144 MHz IF)", 1152, 1296.2, 144.2),
                                       ("2304 MHz (28 MHz IF)", 2276, 2304.1, 28.1),
                                       ("2304 MHz (144 MHz IF)", 2160, 2304.1, 144.1)]:
            c = Converter(title, DOWN, RXTX, off * MHZ, off * MHZ)
            self.assertAlmostEqual(c.radio(air * MHZ), radio * MHZ, places=3, msg=title)
            self.assertAlmostEqual(c.air(radio * MHZ, tx=True), air * MHZ, places=3, msg=title)

    def test_sdr_console_qo100_lnbs(self):
        for off, beacon_if in [(9_750_000_000, 739_750_000), (9_750_100_000, 739_650_000)]:
            c = Converter("LNB", DOWN, RX, float(off), float(off))
            self.assertEqual(c.radio(10_489_750_000.0), beacon_if)

    def test_down_inverted_mirrors_and_swaps_sidebands(self):
        # The IC-9700 work's high-side upconverter: LO 3696.2 MHz, IF = LO - uplink.
        c = Converter("high-side", DOWN, RXTX, 3_696_200_000.0, 3_696_200_000.0, inverted=True)
        self.assertEqual(c.radio(2_400_250_000.0, tx=True), 1_295_950_000.0)
        self.assertEqual(c.air(1_295_950_000.0, tx=True), 2_400_250_000.0)
        # Tuning up on the radio goes down on the air.
        self.assertLess(c.air(1_296_000_000.0), c.air(1_295_000_000.0))
        self.assertEqual(c.air_mode("usb"), "lsb")
        self.assertEqual(c.air_mode("cw"), "cw-r")
        self.assertEqual(c.radio_mode(c.air_mode("lsb")), "lsb")
        self.assertEqual(c.radio_range(2400e6, 2400.5e6, tx=True), (1295.7e6, 1296.2e6))
        self.assertEqual(c.check(2400e6, 2400.5e6, tx=True), "")
        self.assertIn("inverted", c.example(2400e6, 2400.5e6, tx=True))

    def test_up_inverted_lands_above_and_mirrored(self):
        # A high-side HF upconverter (LO 181 MHz): 1-30 MHz in as 180-151.
        c = Converter("high-side HF", UP, RX, 181 * MHZ, 181 * MHZ, inverted=True)
        self.assertEqual(c.radio(1 * MHZ), 180 * MHZ)
        self.assertEqual(c.radio(30 * MHZ), 151 * MHZ)
        self.assertEqual(c.air(151 * MHZ), 30 * MHZ)
        self.assertEqual(c.check(1 * MHZ, 30 * MHZ), "")
        self.assertEqual(c.air_mode("usb"), "lsb")

    def test_not_inverted_keeps_the_sideband(self):
        c = Converter("x", UP, RX, 150 * MHZ, 150 * MHZ)
        self.assertEqual(c.air_mode("usb"), "usb")

    def test_rx_and_tx_offsets_are_separate(self):
        c = Converter("odd", DOWN, RXTX, 1268 * MHZ, 1267 * MHZ)
        self.assertEqual(c.radio(1296 * MHZ), 28 * MHZ)
        self.assertEqual(c.radio(1296 * MHZ, tx=True), 29 * MHZ)

    def test_check_says_when_the_type_disagrees_or_the_radio_would_be_negative(self):
        # Inverted, the type is which side the radio lands: 300 - 145 = 155, above.
        self.assertIn("below", Converter("d", DOWN, RX, 300 * MHZ, 1, inverted=True).check(144 * MHZ, 146 * MHZ))
        self.assertIn("above", Converter("u", UP, RX, 200 * MHZ, 1, inverted=True).check(144 * MHZ, 146 * MHZ))
        self.assertIn("not a frequency", Converter("n", DOWN, RX, 200 * MHZ, 1).check(144 * MHZ, 146 * MHZ))


class Storage(unittest.TestCase):
    def test_round_trip_and_defaults(self):
        c = cv.Converter.from_dict({"title": " 1296 ", "type": "down", "rxOffset": 1152e6})
        self.assertEqual(c.title, "1296")
        self.assertEqual(c.tx_offset, 1152e6)          # a transverter's TX offset is its RX one
        self.assertEqual(c.use, cv.RX)
        self.assertEqual(Converter.from_dict(c.to_dict()), c)

    def test_bad_entries_are_refused_with_the_field(self):
        for bad, words in [({"type": "down", "rxOffset": 1.0}, "title"),
                           ({"title": "a", "type": "sideways", "rxOffset": 1.0}, "type"),
                           ({"title": "a", "rxOffset": -5.0}, "RX offset"),
                           ({"title": "a", "rxOffset": 1.0, "txOffset": "x"}, "TX offset"),
                           ({"title": "a", "rxOffset": 1.0, "maxDriveDbm": 99.0}, "most drive"),
                           ({"title": "a", "rxOffset": 1.0, "inverted": "yes"}, "inverted")]:
            with self.assertRaisesRegex(ValueError, words):
                cv.clean_list([bad])

    def test_titles_must_differ_whatever_the_case(self):
        with self.assertRaisesRegex(ValueError, "titles must differ"):
            cv.clean_list([{"title": "LNB", "rxOffset": 1.0}, {"title": "lnb", "rxOffset": 2.0}])

    def test_order_is_kept(self):
        names = ["c", "a", "b"]
        out = cv.clean_list([{"title": n, "rxOffset": 1.0} for n in names])
        self.assertEqual([d["title"] for d in out], names)

    def test_a_list_key_in_the_registry_validates_and_hands_out_copies(self):
        reg = Registry(["usb"], set())
        add_shared_keys(reg)
        reg.add("converters", "list", [{"title": "a", "type": "down", "rxtx": False, "rxOffset": 1.0,
                                        "txOffset": 1.0, "inverted": False, "maxDriveDbm": None}],
                "setting", validate=cv.clean_list)
        with self.assertRaisesRegex(ValueError, "titles must differ"):
            reg.coerce("converters", [{"title": "a", "rxOffset": 1.0}, {"title": "A", "rxOffset": 1.0}])
        with self.assertRaises(ValueError):
            reg.coerce("converters", {"title": "a"})
        d1, d2 = reg.defaults(), reg.defaults()
        d1["converters"].append({})
        self.assertEqual(len(d2["converters"]), 1)
        self.assertEqual(len(reg.spec["converters"]["default"]), 1)

    def test_find_unique_title_and_drive_cap(self):
        lst = cv.clean_list([{"title": "XV144", "rxOffset": 116e6, "rxtx": True, "maxDriveDbm": 0.0}])
        self.assertEqual(cv.find(lst, "xv144").rx_offset, 116e6)
        self.assertIsNone(cv.find(lst, ""))
        self.assertIsNone(cv.find(lst, "nope"))
        self.assertEqual(cv.unique_title(lst, "XV144"), "XV144 (2)")
        self.assertEqual(cv.unique_title(lst, "new"), "new")
        # 0 dBm out of a 5 W radio: drive amplitude sqrt(1 mW / 5 W).
        self.assertAlmostEqual(cv.drive_cap(cv.find(lst, "XV144"), 5.0), (1e-3 / 5.0) ** 0.5)
        self.assertEqual(cv.drive_cap(cv.find(lst, "XV144"), 1e-4), 1.0)
        self.assertEqual(cv.drive_cap(None, 5.0), 1.0)


class Use(unittest.TestCase):
    """RX only, TX only or RX/TX (07/10/2026), which replaced the `rxtx`
    bool. A list stored before it must load as the same converters."""

    # Two definitions as every release up to HAM 0.1.8 / NB 0.1.8 wrote them,
    # and one hand-written with neither key.
    OLD = [{"title": "QO-100: LNB 9750 MHz", "type": "down", "rxtx": False, "rxOffset": 9750e6, "txOffset": 9750e6,
            "inverted": False, "maxDriveDbm": None},
           {"title": "144 MHz (28 MHz IF)", "type": "down", "rxtx": True, "rxOffset": 116e6, "txOffset": 116e6,
            "inverted": False, "maxDriveDbm": 0.0},
           {"title": "bare", "rxOffset": 125e6}]

    def test_an_old_list_loads_as_the_same_converters_and_saves_in_the_new_key(self):
        new = cv.clean_list(self.OLD)
        self.assertEqual([d["use"] for d in new], [cv.RX, cv.RXTX, cv.RX])
        for d in new:
            self.assertNotIn("rxtx", d)
        for old, d in zip(self.OLD, new):
            a, b = Converter.from_dict(old), Converter.from_dict(d)
            self.assertEqual(a, b)
            for f in (144e6, 1296.2e6, 10489.6e6):
                self.assertEqual((a.radio(f), a.radio(f, tx=True)), (b.radio(f), b.radio(f, tx=True)))
        self.assertEqual(cv.clean_list(new), new)                  # and reads back the same

    def test_tx_only_needs_its_tx_offset_and_never_receives(self):
        c = Converter.from_dict({"title": "uplink", "use": "tx", "txOffset": 1104e6, "rxOffset": 5.0})
        self.assertEqual((c.receives, c.transmits), (False, True))
        self.assertEqual(c.rx_offset, 1104e6)                       # the stray RX offset is not kept
        self.assertEqual(c.radio(2400e6, tx=True), 1296e6)
        with self.assertRaisesRegex(ValueError, "TX offset"):
            Converter.from_dict({"title": "uplink", "use": "tx", "rxOffset": 1104e6})
        self.assertEqual(Converter.from_dict(c.to_dict()), c)

    def test_a_tx_only_converter_fed_from_below_is_an_up_converter(self):
        # Same type (the radio below the air), named by the direction it is used in.
        for use, kind in [(RX, DOWN), (RXTX, DOWN), (cv.TX, UP)]:
            self.assertEqual(Converter("x", DOWN, use, 1104 * MHZ, 1104 * MHZ).kind(), kind, use)
        self.assertEqual(Converter("x", UP, cv.TX, 1 * MHZ, 1 * MHZ).kind(), DOWN)

    def test_use_is_checked_and_wins_over_an_old_rxtx(self):
        for bad in ["both", True, None]:
            with self.assertRaisesRegex(ValueError, "use must be"):
                cv.clean_list([{"title": "a", "use": bad, "rxOffset": 1.0}])
        with self.assertRaisesRegex(ValueError, "rxtx"):
            cv.clean_list([{"title": "a", "rxtx": "yes", "rxOffset": 1.0}])
        with self.assertRaisesRegex(ValueError, "use must be"):
            Converter("a", DOWN, True, 1.0, 1.0)                    # code still written for the bool
        d = Converter.from_dict({"title": "a", "use": "rx", "rxtx": True, "rxOffset": 1.0})
        self.assertEqual(d.use, RX)


class Presets(unittest.TestCase):
    def test_every_preset_loads_checks_and_is_sourced_for_its_band(self):
        for key, (_name, pack) in cv.PACKS.items():
            stored = cv.clean_list([c.to_dict() for c in pack])
            self.assertEqual(len(stored), len(pack), key)
            for c in pack:
                self.assertFalse(c.inverted, c.title)
                self.assertIsNone(c.max_drive_dbm, c.title)    # never a guessed drive limit

    def test_the_transverters_put_their_band_on_their_if(self):
        for c in cv.VHF_UHF_SHF:
            if not c.transmits:
                continue
            band = float(c.title.split(" MHz")[0]) * MHZ
            ifr = float(c.title.split("(")[1].split(" MHz")[0]) * MHZ
            self.assertAlmostEqual(c.radio(band), ifr, msg=c.title)

    def test_the_qo100_lnbs_put_the_narrowband_downlink_near_740_mhz(self):
        for c in cv.QO100:
            if c.transmits:
                continue
            lo, hi = c.radio_range(10_489_500_000.0, 10_490_000_000.0)
            self.assertTrue(739e6 < lo < hi < 741e6, c.title)

    def test_the_uplink_upconverters_reach_2400_from_their_if(self):
        for c in cv.QO100:
            if not c.transmits:
                continue
            ifr = float(c.title.split(": ")[1].split(" MHz")[0]) * MHZ
            self.assertAlmostEqual(c.radio(2_400_000_000.0, tx=True), ifr, msg=c.title)

    def test_adding_a_pack_twice_adds_it_once_and_keeps_the_operators_entries(self):
        mine = cv.clean_list([{"title": "Mine", "rxOffset": 1e6}])
        once = cv.add_pack(mine, cv.VHF_UHF_SHF)
        twice = cv.add_pack(once, cv.VHF_UHF_SHF)
        self.assertEqual(once, twice)
        self.assertEqual(once[0]["title"], "Mine")
        self.assertEqual(len(once), 1 + len(cv.VHF_UHF_SHF))
        cv.clean_list(twice)


if __name__ == "__main__":
    unittest.main()
