"""The pile-up line's rules (ohscore/pileup.py; the UI overhaul's section 5.7),
on synthetic decodes: who the pile-up is on, who calls it, and what it
says about us."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore.pileup import ANSWERED, CALLING, HEARD, NOT, summarise

T0 = 1_760_700_000.0 - (1_760_700_000.0 % 30)      # an even FT8 slot


def dec(k, text, snr=-10, call=""):
    ev = {"slot": T0 + 15.0 * k, "text": text, "snr": snr}
    if call:
        ev["call"] = call
    return ev


# 7P8GE calls CQ in the even slots; four stations answer in the odd ones.
PILE = [
    dec(0, "CQ 7P8GE JJ38"),
    dec(1, "7P8GE RD7P LN23", -6),
    dec(1, "7P8GE R5DT KO94", -4),
    dec(1, "7P8GE EA7KP IM97", +1),
    dec(3, "7P8GE LZ1GHT KN12", -9),
    dec(3, "7P8GE RD7P LN23", -3),        # RD7P again, stronger: counted once, at its best
    # A QSO of two elsewhere in the band: one caller is not a pile-up.
    dec(3, "DL1ABC G4XYZ IO91", -12),
]


class Target(unittest.TestCase):
    def test_the_station_with_most_callers(self):
        p = summarise(PILE, 15.0, mycall="GM4BRI")
        self.assertEqual(p.dx, "7P8GE")
        self.assertEqual(p.count, 4)
        self.assertEqual([c for c, _ in p.callers], ["EA7KP", "RD7P", "R5DT", "LZ1GHT"])
        self.assertEqual(p.callers[1], ("RD7P", -3))
        self.assertEqual(len(p.shown), 3)
        self.assertEqual(p.more, 1)
        self.assertEqual(p.you, NOT)

    def test_the_dx_call_wins_over_the_most_callers(self):
        decs = PILE + [dec(3, "DL1ABC F5ABC JN18", -2), dec(3, "DL1ABC PA3XYZ JO22", -5)]
        self.assertEqual(summarise(decs, 15.0, "GM4BRI", dx="DL1ABC").dx, "DL1ABC")
        self.assertEqual(summarise(decs, 15.0, "GM4BRI").dx, "7P8GE")

    def test_none_with_one_caller(self):
        self.assertIsNone(summarise([dec(1, "7P8GE RD7P LN23")], 15.0, "GM4BRI"))
        self.assertIsNone(summarise(PILE, 15.0, "GM4BRI", dx="DL1ABC"))
        self.assertIsNone(summarise([], 15.0, "GM4BRI"))

    def test_callers_only_from_the_last_two_slots_of_a_parity(self):
        # Slot 1's callers are three of that parity's slots back by slot 7.
        late = [dec(1, "7P8GE RD7P LN23"), dec(1, "7P8GE R5DT KO94"), dec(7, "7P8GE EA7KP IM97"),
                dec(6, "CQ 7P8GE JJ38")]
        self.assertIsNone(summarise(late, 15.0, "GM4BRI"))
        # `now` ends the window: a minute on, nothing is recent.
        self.assertIsNone(summarise(PILE, 15.0, "GM4BRI", now=T0 + 120.0))
        self.assertEqual(summarise(PILE, 15.0, "GM4BRI", now=T0 + 50.0).dx, "7P8GE")

    def test_cqs_free_text_and_reports_are_not_callers(self):
        decs = [dec(1, "CQ DX 7P8GE JJ38"), dec(1, "TNX 73 GL"), dec(1, "7P8GE RR73"), dec(1, "7P8GE RD7P LN23")]
        self.assertIsNone(summarise(decs, 15.0, "GM4BRI"))


class You(unittest.TestCase):
    def test_calling_when_our_last_over_went_to_them(self):
        p = summarise(PILE, 15.0, "GM4BRI", sent="7P8GE GM4BRI IO75")
        self.assertEqual(p.you, CALLING)
        self.assertEqual(p.count, 5)                       # counted...
        self.assertNotIn("GM4BRI", [c for c, _ in p.callers])     # ...never listed
        # An over to someone else is not calling this one.
        self.assertEqual(summarise(PILE, 15.0, "GM4BRI", sent="DL1ABC GM4BRI IO75").you, NOT)

    def test_heard_here_when_our_call_comes_back_through_the_satellite(self):
        p = summarise(PILE + [dec(3, "7P8GE GM4BRI IO75", -14)], 15.0, "GM4BRI", sent="7P8GE GM4BRI IO75")
        self.assertEqual(p.you, HEARD)
        self.assertEqual(p.count, 5)
        self.assertNotIn("GM4BRI", [c for c, _ in p.callers])

    def test_answered_you(self):
        p = summarise(PILE + [dec(4, "GM4BRI 7P8GE -05")], 15.0, "GM4BRI", sent="7P8GE GM4BRI IO75")
        self.assertEqual(p.you, ANSWERED)
        self.assertEqual(p.working, "")

    def test_working_someone_else(self):
        p = summarise(PILE + [dec(2, "GM4BRI 7P8GE -05"), dec(4, "RD7P 7P8GE -08")], 15.0, "GM4BRI",
                      sent="7P8GE GM4BRI IO75")
        # Their latest answer went to RD7P; we are still calling.
        self.assertEqual(p.working, "RD7P")
        self.assertEqual(p.you, CALLING)

    def test_the_decoders_own_sender_wins(self):
        # A hashed call the decoder resolved: the event's `call` is the sender.
        decs = [dec(1, "7P8GE <...> LN23", call="RD7P"), dec(1, "7P8GE R5DT KO94")]
        self.assertEqual([c for c, _ in summarise(decs, 15.0, "GM4BRI").callers], ["R5DT", "RD7P"])

    def test_q65s_minute(self):
        decs = [{"slot": T0 + 60.0, "text": "7P8GE RD7P LN23", "snr": -20},
                {"slot": T0 + 60.0, "text": "7P8GE R5DT KO94", "snr": -18}]
        self.assertEqual(summarise(decs, 60.0, "GM4BRI", now=T0 + 170.0).count, 2)
        self.assertIsNone(summarise(decs, 60.0, "GM4BRI", now=T0 + 400.0))


if __name__ == "__main__":
    unittest.main()
