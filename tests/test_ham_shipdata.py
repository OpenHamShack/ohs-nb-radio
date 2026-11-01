"""A ship's flag from its MMSI and its destination's port name, from the
bundled tables (ohsradio/shipdata.py, 01/11/2026): the real files under
ohsradio/data/ships/, read as Radio reads them.

- **Flags:** the MID found in each MMSI form (ship, group, coast station,
  SAR aircraft, aid to navigation, craft, handheld), none for a distress
  beacon or an unallocated MID, and the Unicode flag from the ISO code.
- **Ports:** a UN/LOCODE however it is spaced, from-and-to, text that is
  not a code left as written, and a port's own name never mistaken for one.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohsradio import shipdata


class Flags(unittest.TestCase):
    def test_each_mmsi_form_finds_its_mid(self):
        cases = {
            235_012_345: "235",      # a ship
            23_501_234: "235",       # 023501234: a group of ships
            2_320_123: "232",        # 002320123: a coast station
            111_232_123: "232",      # a SAR aircraft
            992_351_234: "235",      # an aid to navigation
            982_351_234: "235",      # a craft with a parent ship
            823_512_345: "235",      # a handheld VHF
            "250001234": "250",      # as the API sends it, a string
        }
        for mmsi, mid in cases.items():
            self.assertEqual(shipdata.mid_of(mmsi), mid, mmsi)

    def test_a_distress_beacon_or_nonsense_has_none(self):
        for mmsi in (970_123_456, 972_012_345, 974_012_345, 0, -1, 1_000_000_000, "", None, "ABC"):
            self.assertIsNone(shipdata.mid_of(mmsi), mmsi)
            self.assertIsNone(shipdata.flag(mmsi), mmsi)

    def test_the_country_and_its_flag(self):
        self.assertEqual(shipdata.flag(235_012_345),
                         {"mid": "235", "country": "United Kingdom", "iso": "GB", "emoji": "🇬🇧"})
        self.assertEqual(shipdata.flag(250_001_234)["emoji"], "🇮🇪")
        self.assertEqual(shipdata.flag(2_500_123)["country"], "Ireland")          # Malin Head's coast station
        self.assertEqual(shipdata.flag(992_501_234)["country"], "Ireland")        # an Irish buoy
        # A territory with its own MID but its country's code.
        self.assertEqual(shipdata.flag(204_123_456)["iso"], "PT")                # the Azores

    def test_an_unallocated_mid_or_one_with_no_code(self):
        self.assertIsNone(shipdata.flag(200_123_456))
        dutch = shipdata.flag(306_123_456)
        self.assertEqual((dutch["country"], dutch["iso"], dutch["emoji"]), ("Dutch Caribbean", None, None))


class Ports(unittest.TestCase):
    def test_a_code_however_spaced(self):
        for text in ("GBARD", "GB ARD", "GB-ARD", " gbard ", "GB.ARD"):
            self.assertEqual(shipdata.destination(text), {"text": "Ardrossan", "code": text.strip()}, text)

    def test_from_and_to(self):
        self.assertEqual(shipdata.destination("GBARD>IEDUB"), {"text": "Ardrossan → Dublin", "code": "GBARD>IEDUB"})
        self.assertEqual(shipdata.destination("GB BEL > NOT A PORT"),
                         {"text": "Belfast → NOT A PORT", "code": "GB BEL > NOT A PORT"})

    def test_a_ferry_sends_both_ends(self):
        # CALEDONIAN ISLES, 01/11/2026: the TV read "GB BDI < → Ardrossan".
        for sent in ("GB BDI <-> GB ARD", "GBBDI<>GBARD", "GBBDI <=> GBARD"):
            self.assertEqual(shipdata.destination(sent)["text"], "Brodick, Isle of Arran ↔ Ardrossan", sent)

    def test_text_that_is_not_a_code_is_left_as_written(self):
        for text in ("ARDROSSAN", "FOR ORDERS", "ZZZZZ", "GB", "FISHING GROUNDS"):
            self.assertEqual(shipdata.destination(text), {"text": text, "code": None}, text)
        for nothing in ("", "   ", None):
            self.assertIsNone(shipdata.destination(nothing))

    def test_a_port_name_is_not_read_as_a_code(self):
        # "FJELL" is Fjell's name in Norway, and also the code of a wharf in Fiji.
        self.assertEqual(shipdata.destination("FJELL")["code"], None)
        self.assertEqual(shipdata.destination("FJ ELL")["code"], "FJ ELL")


if __name__ == "__main__":
    unittest.main()
