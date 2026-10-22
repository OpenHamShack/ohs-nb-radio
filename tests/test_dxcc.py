"""Callsign -> country from a cty.dat, as the FT8 band activity shows it."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ohscore import dxcc
from systems import system

# A cut-down cty.dat in the real file's layout, overrides and all.
SAMPLE = """England:                  14:  27:  EU:   52.77:     1.47:     0.0:  G:
    2E,G,M,=G4XYZ/LH,=GB2LH(14)[27];
Scotland:                 14:  27:  EU:   56.82:     4.18:     0.0:  GM:
    2M,GM,MM,=GB2SCO;
Canary Islands:           33:  36:  AF:   28.32:    15.85:     0.0:  EA8:
    AM8,EA8,EB8,=EA1AK/8;
Spain:                    14:  37:  EU:   40.37:     4.88:    -1.0:  EA:
    AM,EA,EB;
United States:            05:  08:  NA:   37.53:    91.67:     5.0:  K:
    AA,K,N,W;
Hawaii:                   31:  61:  OC:   21.12:   157.48:    10.0:  KH6:
    AH6,KH6,KH7(31)[61];
Shetland Islands:         14:  27:  EU:   60.50:     1.50:     0.0:  *GM/s:
    =GM3ZET;
"""


class Lookup(unittest.TestCase):
    def setUp(self):
        self.c = dxcc.Countries(SAMPLE)

    def name(self, call):
        e = self.c.lookup(call)
        return e.name if e else None

    def test_longest_prefix_wins(self):
        self.assertEqual(self.name("G4ABC"), "England")
        self.assertEqual(self.name("GM4ABC"), "Scotland")
        self.assertEqual(self.name("MM0ABC"), "Scotland")
        self.assertEqual(self.name("2E0AAA"), "England")
        self.assertEqual(self.name("EA8ABC"), "Canary Islands")
        self.assertEqual(self.name("EA4ABC"), "Spain")
        self.assertEqual(self.name("KH6AB"), "Hawaii")
        self.assertEqual(self.name("KH7AB"), "Hawaii")         # an override in brackets is stripped
        self.assertEqual(self.name("K1ABC"), "United States")

    def test_exact_calls_beat_prefixes(self):
        self.assertEqual(self.name("GM3ZET"), "Shetland Islands")
        self.assertTrue(self.c.lookup("GM3ZET").wae)
        self.assertEqual(self.name("GB2LH"), "England")

    def test_portable_calls_are_where_the_station_is(self):
        self.assertEqual(self.name("EA8/G4ABC"), "Canary Islands")
        self.assertEqual(self.name("G4ABC/EA8"), "Canary Islands")
        self.assertEqual(self.name("G4ABC/P"), "England")
        self.assertEqual(self.name("GM4ABC/M"), "Scotland")
        self.assertEqual(self.name("EA4ABC/8"), "Canary Islands")   # call area changed
        self.assertEqual(self.name("<EA8/G4ABC>"), "Canary Islands")  # FT8's hashed-call brackets

    def test_at_sea_or_unknown_is_no_country(self):
        self.assertIsNone(self.c.lookup("G4ABC/MM"))
        self.assertIsNone(self.c.lookup("<...>"))
        self.assertIsNone(self.c.lookup(""))
        self.assertIsNone(self.c.lookup("Q1ABC"))

    def test_no_file_means_no_countries(self):
        empty = dxcc.Countries()
        self.assertFalse(empty)
        self.assertIsNone(empty.lookup("G4ABC"))


class Loading(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        dxcc._cache.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        dxcc._cache.clear()

    def test_the_operators_own_file_wins(self):
        (self.tmp / "cty.dat").write_text(SAMPLE, encoding="latin-1")
        self.assertEqual(dxcc.load(self.tmp).lookup("EA8ABC").name, "Canary Islands")

    def test_bundled_copy_beats_an_installed_wsjtx_and_the_operators_beats_both(self):
        # Ours is refreshed each release, an installed WSJT-X's whenever its
        # package was built, and the file has no date to compare them by
        # (ohscore/dxcc.py), so ours goes first; the operator's own, in the
        # data folder, goes before both.
        from ohscore import host
        bundled = self.tmp / "ohscore-data" / "cty.dat"
        bundled.parent.mkdir()
        bundled.write_text(SAMPLE, encoding="latin-1")
        installed = self.tmp / "WSJT" / "wsjtx"
        (installed / "share" / "wsjtx").mkdir(parents=True)
        (installed / "share" / "wsjtx" / "cty.dat").write_text(
            "Elsewhere: 1: 1: EU: 0.0: 0.0: 0.0: EA8:\n    EA8;\n", encoding="latin-1")
        data = self.tmp / "data"
        data.mkdir()
        with system("windows"), mock.patch.object(dxcc, "BUNDLED", bundled), \
                mock.patch.object(host, "WSJTX_DIRS", (str(installed / "bin"),)):
            self.assertEqual(dxcc.load(data).lookup("EA8ABC").name, "Canary Islands")
            dxcc._cache.clear()
            bundled.unlink()                                   # a tree without ohscore/data
            self.assertEqual(dxcc.load(data).lookup("EA8ABC").name, "Elsewhere")
            dxcc._cache.clear()
            bundled.write_text(SAMPLE, encoding="latin-1")
            (data / "cty.dat").write_text("Mine: 1: 1: EU: 0.0: 0.0: 0.0: EA8:\n    EA8;\n", encoding="latin-1")
            self.assertEqual(dxcc.load(data).lookup("EA8ABC").name, "Mine")

    def test_none_anywhere_is_empty_not_an_error(self):
        with mock.patch.object(dxcc, "candidates", return_value=[self.tmp / "missing.dat"]):
            self.assertFalse(dxcc.load(self.tmp))


if __name__ == "__main__":
    unittest.main()
