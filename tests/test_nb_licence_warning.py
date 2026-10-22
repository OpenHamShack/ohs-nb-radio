"""Brian, 08/10/2026: a licence class that is not set must warn, not lock.

The international licence framework (merged 08/10/2026) added NB's uplink
check (Radio._uplink_refusal, ohscore.licences.satellite_uplink), but it
only ever refuses - with no regime in force, or no class chosen, it says
nothing, so a station with neither simply transmitted with the uplink
unchecked and no sign of it on the transmit card. Locking then, as
OpenHamShack HAM's guard does, was rejected: HAM has required a class since
05/10/2026, so nobody upgrades into it unset, but NB's check is new, and
every installed NB has no class at all. _licence_warning puts the one
standing transmit-card warning (Engine.tx_warn, "licence") up instead,
and clears it once a class is chosen under a known licence."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest

from helpers import make_radio
from ohsnb.radio import NO_LICENCE_WARN


class LicenceWarning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def radio(self, **over):
        return make_radio(self.tmp.name, **over)

    def test_nothing_known_warns_but_does_not_lock(self):
        r = self.radio()
        r._derive()
        w = r.state()["txWarning"]
        self.assertEqual((w["key"], w["level"], w["text"]), ("licence", "warn", NO_LICENCE_WARN))
        # The uplink guard itself still says nothing: it only ever refuses.
        self.assertEqual(r._uplink_refusal(2_400_050_000.0, 2_400_052_700.0), "")

    def test_a_known_country_with_no_class_still_warns(self):
        r = self.radio(callsign="GM4BRI")      # Ofcom is written in; no class chosen
        r._derive()
        self.assertEqual(r.state()["txWarning"]["key"], "licence")

    def test_a_class_from_a_different_licence_still_warns(self):
        # Kept from a different country (e.g. after a move): as unchecked
        # as none at all, because it is not one of Ofcom's classes.
        r = self.radio(callsign="GM4BRI", licenceClass="insteg")      # Sweden's, not Ofcom's
        r._derive()
        self.assertEqual(r.state()["txWarning"]["key"], "licence")

    def test_choosing_a_class_clears_it(self):
        r = self.radio(callsign="GM4BRI")
        r._derive()
        self.assertEqual(r.state()["txWarning"]["key"], "licence")
        r.set(authorise=True, licenceClass="full")
        self.assertEqual(r.state()["txWarning"], {})

    def test_losing_the_class_again_brings_it_back(self):
        r = self.radio(callsign="GM4BRI", licenceClass="full")
        r._derive()
        self.assertEqual(r.state()["txWarning"], {})
        r.set(authorise=True, licenceClass="")
        self.assertEqual(r.state()["txWarning"]["key"], "licence")


if __name__ == "__main__":
    unittest.main()
