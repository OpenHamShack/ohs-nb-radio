"""The sender's country on every decode api/events sends (ohscore/engine.py
_with_country): what Remote's Band Activity shows in its Country column,
from the same cty.dat lookup as the desktop's FT8 panel. Through a real
QO-100 NB engine on the simulator, as a decoder's own events arrive."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest
from pathlib import Path

from ohscore.audio import NullAudio


def ft8(text, call=None, **kw):
    ev = {"mode": "ft8", "slot": 1_791_000_000.0, "snr": -7, "dt": 0.1, "df": 1200, "text": text}
    if call is not None:
        ev["call"] = call
    ev.update(kw)
    return ev


class DecodeCountry(unittest.TestCase):
    def setUp(self):
        from ohsnb.radio import Radio
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.r = Radio({"device": "sim", "audioBackend": "null"}, persist=False, data_dir=self.tmp.name,
                       audio=NullAudio(realtime=False))
        self.feed = self.r.subscribe("events", 64)
        self.addCleanup(self.r.unsubscribe, self.feed)

    def sent(self, ev):
        self.r._emit_event(ev)
        out = self.feed.drain()
        self.assertEqual(len(out), 1)
        return out[0]

    def test_a_cq_names_the_callers_country(self):
        ev = self.sent(ft8("CQ EA8BFK IL18", call="EA8BFK", grid="IL18"))
        self.assertEqual((ev["country"], ev["dxcc"], ev["continent"]), ("Canary Islands", "EA8", "AF"))

    def test_a_portable_prefix_is_where_the_station_is(self):
        self.assertEqual(self.sent(ft8("CQ EA8/G4ABC", call="EA8/G4ABC"))["country"], "Canary Islands")
        self.assertEqual(self.sent(ft8("CQ G4ABC/P IO91", call="G4ABC/P"))["country"], "England")

    def test_a_call_cty_cannot_place_gets_no_field(self):
        # At sea is in no country; free text names no sender at all.
        self.assertNotIn("country", self.sent(ft8("CQ G4ABC/MM", call="G4ABC/MM")))
        self.assertNotIn("country", self.sent(ft8("TNX FER QSO 73")))

    def test_the_operators_own_cty_dat_wins(self):
        # The data folder's copy first, as the desktop panel reads it
        # (ohscore/dxcc.py): one entity claiming every G call.
        Path(self.tmp.name, "cty.dat").write_text(
            "Test Land:  14:  27:  EU:   52.00:     1.00:     0.0:  G:\n    G;\n", encoding="latin-1")
        self.assertEqual(self.sent(ft8("CQ G4ABC IO91", call="G4ABC"))["country"], "Test Land")


if __name__ == "__main__":
    unittest.main()
