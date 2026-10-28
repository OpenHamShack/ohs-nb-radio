"""The station profile is adopted as the engine is built (ohscore/engine.py
_EngineType, ohscore/station.py StationLink.adopt).

A box or computer whose only locator is the shared station profile -
nothing in its own settings - must have that locator from the moment the
radio exists. Until 28/10/2026 adoption ran half way through
Engine.__init__, before attributes that set() needs (_hold_tls,
activity_hooks, and Radio's _pin_tls), so it failed every time with
"station profile not adopted": the locator stayed empty and every AIS
vessel's distance and bearing was null. These engines are built as the
program an operator runs builds them (persist=True), since a test's
throw-away engine never adopts at all."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import logging
import tempfile
import unittest
from pathlib import Path

import helpers
from ohscore import station as station_mod
from ohscore.audio import NullAudio
from ohsnb.radio import Radio as NbRadio
from ohsradio.radio import Radio as HamRadio

LOCATOR = "IO75RL"


class AdoptedAtOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        # Another app on this station already said where it is.
        st = station_mod.open_station("shack-elsewhere", "1", self.dir, background=False)
        st.profile.update({"locator": LOCATOR})
        st.close()

    def build(self, cls, cfg):
        # The old failure was swallowed into a warning on the engine's
        # logger; building must not log one.
        with self.assertNoLogs(cls.LOGGER, logging.WARNING):
            r = cls(cfg, persist=True, data_dir=self.dir, conf_path=self.dir / "settings.json",
                    audio=NullAudio(realtime=False))
        self.addCleanup(r.station.close)
        self.addCleanup(r.stop)
        return r

    def test_radio_takes_the_profiles_locator_and_ranges_ships_from_it(self):
        r = self.build(HamRadio, {"device": "sim", "audioBackend": "null", "simRealtime": False,
                                  "callsign": "GM4BRI", "licenceClass": "foundation"})
        self.addCleanup(r.radiodns.stop)
        self.assertEqual(r.st["locator"], LOCATOR)
        # The supervisor's tick hands the table the station's locator; a
        # ship heard after it has its distance and bearing from there.
        r.ais.tick()
        v = r.ais.table.heard({"type": 1, "mmsi": 235000001, "lat": 55.6, "lon": -5.0}, 1_790_000_000.0)
        from ohscore.countries import distance_bearing, locator_position
        km, brg = distance_bearing(*locator_position(LOCATOR), 55.6, -5.0)
        self.assertAlmostEqual(v["distanceKm"], km, delta=0.01)
        self.assertAlmostEqual(v["bearingDeg"], brg, delta=0.1)

    def test_nb_takes_the_profiles_locator(self):
        cfg = helpers.sim_cfg(callsign="GM4BRI")
        cfg.pop("locator", None)
        r = self.build(NbRadio, cfg)
        self.assertEqual(r.st["locator"], LOCATOR)


if __name__ == "__main__":
    unittest.main()
