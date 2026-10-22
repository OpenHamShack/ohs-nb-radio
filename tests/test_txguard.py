"""Both apps take band limits and transmit permission from the shared
dataset (ohs-libs shack_bandplan, through ohscore/txguard.py) applied to the
station profile (BETA-PLAN architecture change 5; gate 1: switching the
profile to a non-UK country changes band limits in an app's own tests).

What is proved here is the apps' side: that each app's state becomes the
right profile, that the engines ask the dataset and act on its answer, and
that the two width rules the old guards had (one signal's width for the
plan, the passband for where it reaches) survived the move. That the
dataset gives the old modules' answers is ohs-libs' test_conformance.py."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest

import ham_helpers
import helpers
from ohscore import txguard
from ohsnb import bandplan


class Profile(unittest.TestCase):
    def test_settings_become_the_station_profile(self):
        p = txguard.profile({"callsign": "ea8/gm4bri", "stationCountry": "ea8", "licence": "auto",
                             "licenceClass": "full", "nearLondon": True,
                             "stationConditions": {"scotland40km": False}})
        self.assertEqual(p["dxccPrefix"], "EA8")      # a DXCC prefix, not an ISO country
        self.assertEqual(p["licence"], {"regime": "auto", "class": "full"})
        self.assertEqual(p["conditions"], {"nearLondon": True, "scotland40km": False})

    def test_own_licence_carries_its_segments(self):
        seg = {"lo": 144e6, "hi": 146e6, "watts": 50.0, "unit": "PEP", "satellite": False, "note": ""}
        p = txguard.profile({"callsign": "JA1ABC", "licence": "custom", "customLicence": [seg]})
        v = txguard.GUARD.check(p, 145_500_000, 145_512_000, mode="fm")
        self.assertEqual((v.refused, v.limit_w), ("", 50.0))
        self.assertTrue(txguard.GUARD.check(p, 432_200_000, 432_202_700, mode="usb").refused)


class RadioFollowsTheCountry(unittest.TestCase):
    """The same 2 m FM signal, the same Full-equivalent class: the limit is
    the station country's, from the dataset."""

    def limit(self, **over):
        r = ham_helpers.make_radio(vfo=145_500_000.0, mode="fm", **over)
        self.addCleanup(ham_helpers.close, r)
        r.start()
        ham_helpers.pump(r, 0.3)
        info = r.state()["licenceInfo"]
        return info["limitW"], info["limitKind"], r.state()["txBlocked"]

    def test_uk_full_is_1000_w_on_2m(self):
        self.assertEqual(self.limit(callsign="GM4BRI", licenceClass="full"), (1000, "PEP", ""))

    def test_germany_class_a_is_750_w_on_2m(self):
        w, kind, blocked = self.limit(callsign="DL1ABC", licenceClass="de_a")
        self.assertEqual((w, kind, blocked), (750, "PEP", ""))

    def test_germany_class_n_keeps_2m_and_its_own_limit(self):
        w, _kind, blocked = self.limit(callsign="DL1ABC", licenceClass="de_n")
        self.assertEqual(blocked, "")
        self.assertLess(w, 750)


class Qo100UplinkFollowsTheCountry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def refusal(self, **over):
        r = helpers.make_radio(self.tmp.name, **over)
        return r._uplink_refusal(2_400_300_000.0, 2_400_302_700.0)

    def test_uk_full_may_uplink(self):
        self.assertEqual(self.refusal(callsign="GM4BRI", licenceClass="full"), "")

    def test_german_class_n_has_no_13cm(self):
        self.assertIn("Class N", self.refusal(callsign="DL1ABC", licenceClass="de_n"))

    def test_unknown_licence_is_not_a_refusal_in_nb(self):
        # NB warns rather than locking (ohsnb/radio.py _licence_warning).
        self.assertEqual(self.refusal(callsign="GM4BRI"), "")
        self.assertEqual(self.refusal(callsign="ZS1ABC", licenceClass="full"), "")


class SignalWidth(unittest.TestCase):
    """FT8 from another program, through a loopback device, sits somewhere
    in a 3 kHz dial window: its own 55 Hz is what a 500 Hz segment judges,
    the window is what says where it can reach."""

    def test_qo100_narrow_digimodes(self):
        lo, hi = 10_489_550_000.0, 10_489_552_400.0
        self.assertEqual(bandplan.tx_blocked(lo, hi, "ft8", width=55.0), "")
        self.assertIn("500 Hz", bandplan.tx_blocked(lo, hi, "ft8"))
        # Reach still counts: a window touching the CW segment is refused.
        self.assertIn("CW", bandplan.tx_blocked(10_489_538_800.0, 10_489_541_200.0, "ft8", width=55.0))

    def test_widths_off_judges_reach_alone(self):
        self.assertEqual(bandplan.tx_blocked(10_489_550_000.0, 10_489_552_400.0, "rtty", widths=False), "")

    def test_radio_20m_window_under_enforce(self):
        p = txguard.profile({"callsign": "GM4BRI", "licenceClass": "full"})
        self.assertEqual(txguard.GUARD.check(p, 14_074_000, 14_077_000, mode="ft8", signal_bw=50,
                                             plan_guard="enforce").refused, "")
        self.assertIn("Band plan", txguard.GUARD.check(p, 14_074_000, 14_077_000, mode="ft8",
                                                       plan_guard="enforce").refused)


class DrawnPlanMatchesTheDataset(unittest.TestCase):
    """The scope draws ohsnb/bandplan.py SEGMENTS; the guard judges the
    dataset. A signal on any segment edge, in any class, must get the same
    answer from both, so what the operator sees shaded is what is refused."""

    def table_rule(self, lo, hi, mode):
        cls = bandplan.MODE_CLASS[mode]
        if hi - lo > bandplan.MAX_BW + 1e-6 or lo < bandplan.DL_LO or hi > bandplan.DL_HI:
            return False
        for s_lo, s_hi, _label, classes, maxbw in bandplan.SEGMENTS:
            if not (lo < s_hi - 1e-6 and hi > s_lo + 1e-6):
                continue
            if classes is None or cls not in classes or hi - lo > maxbw + 1e-6:
                return False
        return True

    def test_every_edge(self):
        edges = sorted({e for s in bandplan.SEGMENTS for e in s[:2]})
        n = 0
        for e in edges:
            for off in (-1500.0, -300.0, 0.0, 300.0, 1500.0):
                for width in (55.0, 400.0, 2400.0):
                    for mode in ("usb", "cw", "ft8", "freedv"):
                        lo = e + off - width / 2
                        hi = lo + width
                        n += 1
                        self.assertEqual(bandplan.tx_blocked(lo, hi, mode) == "", self.table_rule(lo, hi, mode),
                                         (lo, hi, mode, bandplan.tx_blocked(lo, hi, mode)))
        self.assertGreater(n, 500)


if __name__ == "__main__":
    unittest.main()
