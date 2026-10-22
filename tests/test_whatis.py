"""What "What is this?" says about a frequency and the action it offers
(ohsnb/whatis.py), for each row of docs/ui-overhaul-2026-10.md section 5.6's
table, from synthetic skimmer entries shaped as Skimmer.entries() makes
them (tests/test_skimmer.py proves the skimmer makes such lists). No Qt:
the card that words these is tests/test_ui_whatis.py's."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import time
import unittest

from ohsnb import bandplan, whatis

ON = {"skimState": "running", "cwPitch": 700.0}


def entry(**kw):
    e = {"id": 1, "f": 0.0, "lo": 0.0, "hi": 0.0, "kind": "signal", "label": "", "mode": "usb", "dial": None,
         "exact": False, "measured": "", "voice": False, "why": "", "snr": 12.0, "first": time.time() - 30,
         "last": time.time(), "active": True, "looks": 1, "count": 1}
    e.update(kw)
    if not e["f"]:
        e["f"] = (e["lo"] + e["hi"]) / 2
    return e


def ident(e, f=None, st=ON, events=()):
    return whatis.identify(e["f"] if f is None else f, [e], st, events, time.time())


class Rows(unittest.TestCase):
    def test_a_calling_window_decodes_its_mode_at_its_dial(self):
        for label, mode, dial in (("FT8", "ft8", 10_489_540_000.0), ("FT4/FT8 (contest)", "ft8", 10_489_870_000.0),
                                  ("Q65", "q65", 10_489_545_000.0), ("JS8", "js8", 10_489_548_000.0)):
            e = entry(id=-1, f=dial, lo=dial + 400, hi=dial + 2_600, kind="digital", label=label, mode=mode,
                      dial=dial, exact=True, count=12, calls=["7P8GE", "EA1EAU"])
            i = ident(e, f=dial + 1_200)
            self.assertEqual(i.what, "window", label)
            self.assertEqual(i.actions, (whatis.Action("decode", mode=mode, dial=dial),), label)

    def test_the_cw_beacons_decode_with_the_mark_on_the_pitch(self):
        for key, label, mark in (("lower", "Lower beacon (CW)", 10_489_500_400.0),
                                 ("upper", "Upper beacon (CW)", 10_489_999_600.0)):
            e = entry(f=bandplan.BEACONS[key]["ref"], lo=mark - 450, hi=mark + 50, kind="beacon", label=label,
                      mode="cw")
            i = ident(e, st={**ON, "cwPitch": 600.0})
            self.assertEqual(i.what, "beacon_cw")
            a = i.actions[0]
            self.assertEqual((a.key, a.mode), ("decode", "cw"))
            self.assertEqual(a.dial + 600.0, mark)        # the key-down tone, heard at the pitch

    def test_the_middle_and_multimedia_beacons_show_their_page(self):
        mid = entry(f=10_489_750_000.0, lo=10_489_749_600.0, hi=10_489_750_400.0, kind="beacon",
                    label="Middle beacon (400 Bd BPSK)")
        self.assertEqual(ident(mid).what, "beacon_mid")
        self.assertEqual(ident(mid).actions, (whatis.Action("view", page="midtext"),))
        mmb = entry(f=10_489_995_000.0, lo=10_489_993_600.0, hi=10_489_996_300.0, kind="beacon",
                    label="Multimedia beacon (HSmodem)")
        self.assertEqual((ident(mmb).what, ident(mmb).actions[0].page), ("mmb", "bulletins"))

    def test_the_broadcast_slot_is_listened_to(self):
        e = entry(lo=10_489_850_300.0, hi=10_489_852_600.0, kind="beacon", label="AMSAT-DL broadcast")
        i = ident(e)
        self.assertEqual(i.what, "broadcast")
        self.assertEqual(i.actions[0].key, "listen")
        self.assertLessEqual(i.actions[0].dial, e["lo"])       # the whole voice above the dial

    def test_kgstv_shows_pictures_and_can_be_listened_to(self):
        e = entry(f=10_489_624_900.0, lo=10_489_625_100.0, hi=10_489_627_800.0, kind="known",
                  label="KG-STV picture", dial=10_489_624_900.0, exact=True)
        i = ident(e, f=10_489_626_400.0)
        self.assertEqual(i.what, "kgstv")
        self.assertEqual([(a.key, a.page, a.dial) for a in i.actions],
                         [("view", "kgstv", None), ("listen", "", 10_489_624_900.0)])

    def test_ssb_measured_is_listened_to_on_its_dial(self):
        d = 10_489_773_700.0
        e = entry(f=d, lo=d + 300, hi=d + 2_700, kind="ssb", label="SSB", dial=d, exact=True, measured="twice",
                  voice=True)
        i = ident(e, f=d + 1_500)
        self.assertEqual(i.what, "ssb_measured")
        self.assertEqual(i.actions, (whatis.Action("listen", dial=d),))

    def test_ssb_not_measured_is_auto_tuned_voice_heard_or_not(self):
        d = 10_489_800_000.0
        for voice, what in ((True, "ssb_voice"), (False, "ssb_shape")):
            e = entry(f=d, lo=d + 300, hi=d + 2_600, kind="ssb", label="SSB" if voice else "SSB?", dial=d,
                      voice=voice)
            i = ident(e, f=d + 1_000)
            self.assertEqual(i.what, what)
            self.assertEqual(i.actions, (whatis.Action("autotune"),))

    def test_cw_decodes_cw_on_the_signal(self):
        e = entry(f=10_489_521_000.0, lo=10_489_520_975.0, hi=10_489_521_025.0, kind="cw", label="CW", mode="cw")
        i = ident(e)
        self.assertEqual(i.what, "cw")
        self.assertEqual(i.actions, (whatis.Action("decode", mode="cw", f=10_489_521_000.0),))

    def test_data_is_listened_to_and_tried_as_psk31_or_rtty(self):
        e = entry(f=10_489_653_200.0, lo=10_489_653_100.0, hi=10_489_653_300.0, kind="data", label="Data (narrow)")
        i = ident(e)
        self.assertEqual(i.what, "data")
        self.assertEqual(i.actions[0].key, "listen")
        self.assertAlmostEqual(i.actions[0].dial, 10_489_652_200.0)       # heard as a 1 kHz tone
        self.assertEqual([(a.key, a.mode) for a in i.tries], [("try", "psk31"), ("try", "rtty")])

    def test_an_unidentified_known_signal_is_named_with_what_the_survey_learnt(self):
        e = entry(f=10_489_636_650.0, lo=10_489_635_500.0, hi=10_489_637_800.0, kind="known",
                  label="ARQ data link (VARA HF?)")
        i = ident(e)
        self.assertEqual((i.what, i.hint), ("known", "arq"))
        self.assertEqual(i.actions[0].key, "listen")

    def test_a_signal_only_the_1710_survey_saw_gets_its_hint(self):
        e = entry(f=10_489_569_500.0, lo=10_489_569_450.0, hi=10_489_569_550.0, kind="data", label="Data (narrow)")
        self.assertEqual(ident(e).hint, "slowfsk")

    def test_a_carrier_and_a_signal_not_looked_at_yet(self):
        c = entry(f=10_489_698_600.0, lo=10_489_698_590.0, hi=10_489_698_610.0, kind="carrier", label="Carrier")
        self.assertEqual(ident(c).what, "carrier")
        self.assertEqual(ident(c).actions[0].key, "listen")
        u = entry(lo=10_489_820_000.0, hi=10_489_822_400.0, kind="signal", looks=0)
        self.assertEqual(ident(u).what, "unlooked")
        faint = entry(lo=10_489_587_900.0, hi=10_489_588_100.0, kind="signal", looks=2,
                      why="nothing stands out in the channel")
        self.assertEqual(ident(faint).what, "faint")
        self.assertEqual(ident(faint).hint, "keyedcarrier")

    def test_nothing_there_gives_the_segment(self):
        e = entry(f=10_489_700_000.0, lo=10_489_699_000.0, hi=10_489_701_000.0, kind="ssb", label="SSB?")
        i = whatis.identify(10_489_720_000.0, [e], ON, (), time.time())
        self.assertEqual(i.what, "nothing")
        self.assertEqual(i.segment["label"], "SSB only")
        self.assertEqual(i.actions, ())

    def test_skimmer_off_says_so(self):
        i = whatis.identify(10_489_720_000.0, [], {"skimState": "off"}, (), time.time())
        self.assertEqual((i.what, i.skimmer), ("nothing", "off"))


class Picking(unittest.TestCase):
    def test_the_narrowest_holding_entry_wins_then_the_nearest_within_300_hz(self):
        wide = entry(id=1, lo=10_489_600_000.0, hi=10_489_603_000.0, kind="signal", looks=1)
        cw = entry(id=2, f=10_489_601_000.0, lo=10_489_600_990.0, hi=10_489_601_010.0, kind="cw", label="CW")
        self.assertIs(whatis.pick(10_489_601_005.0, [wide, cw]), cw)
        self.assertIs(whatis.pick(10_489_601_250.0, [cw]), cw)          # 240 Hz off its edge
        self.assertIsNone(whatis.pick(10_489_601_400.0, [cw]))

    def test_an_over_power_column_is_explained_while_it_shows(self):
        now = time.time()
        ft8 = entry(id=-1, f=10_489_540_000.0, lo=10_489_540_150.0, hi=10_489_543_100.0, kind="digital", label="FT8",
                    mode="ft8", dial=10_489_540_000.0, exact=True, count=20)
        over = {"kind": "overpower", "lo": 10_489_540_600.0, "hi": 10_489_542_100.0, "freq": 10_489_541_300.0,
                "width": 1_500.0, "excessDb": 14.0, "start": now - 40, "end": now, "active": True}
        i = whatis.identify(10_489_541_000.0, [ft8], ON, [over], now)
        self.assertEqual(i.what, "window")                  # the window still, and why it is over the beacon
        self.assertIs(i.over, over)
        old = dict(over, active=False, end=now - 300)
        self.assertIsNone(whatis.identify(10_489_541_000.0, [ft8], ON, [old], now).over)


if __name__ == "__main__":
    unittest.main()
