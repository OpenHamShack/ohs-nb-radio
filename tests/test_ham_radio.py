"""OpenHamShack HAM's engine on the band simulator: tuning across bands, band
stacks, where the spectrum lands, and the safety rules it inherits."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import time
import unittest

import numpy as np

from ohsradio import bands
from ohsradio.devices.sim import HamSim

from ham_helpers import close, make_radio, pump


class Receive(unittest.TestCase):
    def setUp(self):
        self.r = make_radio()

    def tearDown(self):
        close(self.r)

    def test_starts_receiving_and_never_keyed(self):
        self.r.start()
        st = self.r.state()
        self.assertTrue(st["running"])
        self.assertFalse(st["keyed"])
        self.assertEqual(st["seqState"], "rx")
        self.assertEqual(st["band"], "2m")
        self.assertLess(st["spanLo"], st["vfo"])
        self.assertGreater(st["spanHi"], st["vfo"])
        self.assertEqual(st["licenceInfo"]["class"], "Foundation")

    def test_a_band_the_span_holds_is_all_on_the_scope(self):
        self.r.start()
        self.r.band("20m")
        # Arriving on a band builds its simulated stations first, on the
        # receive thread here (simRealtime off), and the span moves after.
        # That took 3-9 s while the templates were FFTs of awkward lengths
        # (test_sim.Templates); about 1-3 s since. The wait is a ceiling,
        # not a cost - it returns as soon as the scope has moved.
        pump(self.r, 30, until=lambda: self.r.state()["spanLo"] < 14e6)
        st = self.r.state()
        self.assertLess(st["spanLo"], 14_000_000)
        self.assertGreater(st["spanHi"], 14_350_000)
        # Tuning within it never moves the hardware.
        c = self.r.centre
        self.r.set(vfo=14_300_000.0)
        pump(self.r, 0.5)
        self.assertEqual(self.r.centre, c)
        # A band that fits on one side of DC keeps DC off it.
        self.r.band("30m")
        pump(self.r, 30, until=lambda: self.r.state()["spanLo"] < 10.1e6)
        self.assertLess(self.r.centre, 10_100_000)

    def test_a_station_appears_at_its_frequency(self):
        self.r.set(vfo=7_150_000.0, mode="lsb")
        wide = self.r.subscribe("wide", 256)
        self.r.start()
        pump(self.r, 10, until=lambda: "40m" in self.r.dev.pops)
        carrier = next(s for s in self.r.dev.pops["40m"] if s.name == "carrier")
        got = pump(self.r, 4, feeds=[wide])["wide"]
        self.assertGreater(len(got), 5)
        t, start, bin_hz, db = got[-1]
        i = int(round((carrier.dl - start) / bin_hz))
        local = db[max(0, i - 2):i + 3].max()
        self.assertGreater(local - np.median(db), 20.0)

    def test_band_stack_registers(self):
        self.r.start()
        self.r.band("20m")                                     # first visit from FM: the SSB segment
        st = self.r.state()
        self.assertEqual((st["vfo"], st["mode"]), (14_125_000.0, "usb"))
        self.r.band("20m")                                     # second press: next register
        st = self.r.state()
        self.assertEqual((st["vfo"], st["mode"]), (14_074_000.0, "ft8"))
        self.r.set(vfo=14_210_500.0, mode="usb")
        self.r.band("2m")
        self.assertEqual(self.r.state()["band"], "2m")
        self.r.band("20m")                                     # back where it was left
        st = self.r.state()
        self.assertEqual((st["vfo"], st["mode"]), (14_210_500.0, "usb"))
        self.assertIn("20m", st["bandStacks"])

    def test_deferred_band_says_why(self):
        with self.assertRaisesRegex(ValueError, "38.4 MHz"):
            self.r.band("6m")

    def test_nothing_offers_a_deferred_band_as_if_it_worked(self):
        # 6 m has no radio here: no built-in memory may lead there, and a
        # dial typed into it is judged refused with the band's reason, even
        # though every licence class has 6 m. The band's data is kept.
        from ohsradio.radio import presets
        six = bands.BY_NAME["6m"]
        self.assertEqual([m["name"] for m in presets() if six.lo <= m["rf"] <= six.hi], [])
        self.assertTrue(any(m["name"] == "FT8 2m" for m in presets()))
        self.assertEqual(six.ft8, 50_313_000.0)
        self.r.set(authorise=True, licenceClass="full")
        self.r.set(vfo=50_313_000.0, mode="ft8")
        info = self.r.state()["licenceInfo"]
        self.assertEqual(info["level"], "refused")
        self.assertIn("38.4 MHz", info["why"])

    def test_mode_follows_the_sideband_convention_through_the_stacks(self):
        for b in bands.BANDS:
            if b.deferred or b.name == "60m":          # UK 60 m practice is USB
                continue
            for f, m in b.stack:
                if m in ("usb", "lsb"):
                    self.assertEqual(m, bands.natural_sideband(f), (b.name, f))


class Safety(unittest.TestCase):
    def setUp(self):
        self.r = make_radio()

    def tearDown(self):
        close(self.r)

    def test_nothing_keys_without_ptt_send_or_tune(self):
        self.r.start()
        for name in ("20m", "2m", "70cm"):
            self.r.band(name)
        self.r.set(mode="fm", drive=0.5)
        self.r.stop()
        self.r.start()
        pump(self.r, 1.5)
        self.assertFalse(self.r.state()["keyed"])
        self.assertEqual(self.r.dev.tx_written, 0)

    def test_watchdog_unkeys_when_the_ui_stops(self):
        self.r.start()
        self.r.ptt(True)
        self.assertTrue(self.r.state()["keyed"])
        toasts = self.r.subscribe("toast", 64)
        # No heartbeat from here on.
        end = time.monotonic() + 6
        while time.monotonic() < end and self.r.state()["keyed"]:
            time.sleep(0.05)
        self.assertFalse(self.r.state()["keyed"])
        self.assertTrue(any("watchdog" in t["text"] for t in toasts.drain()))

    def test_licence_class_decides_23cm(self):
        self.r.start()
        self.r.band("23cm")
        self.r.set(mode="usb")
        self.assertIn("Foundation licence", self.r.state()["txBlocked"])
        self.r.set(authorise=True, licenceClass="intermediate")
        self.assertEqual(self.r.state()["txBlocked"], "")

    def test_near_london_refuses_431_to_432_mhz(self):
        self.r.start()
        self.r.set(vfo=431_500_000.0, mode="usb")
        self.assertEqual(self.r.state()["txBlocked"], "")              # unticked by default
        self.assertFalse(self.r.state()["nearLondon"])
        self.r.set(authorise=True, nearLondon=True)
        st = self.r.state()
        self.assertIn("within 100 km of Charing Cross", st["txBlocked"])
        self.assertEqual(st["licenceInfo"]["level"], "refused")
        with self.assertRaisesRegex(ValueError, "Charing Cross"):
            self.r.ptt(True)
        self.r.set(vfo=433_500_000.0)                                    # the rest of 70 cm is fine
        self.assertEqual(self.r.state()["txBlocked"], "")
        with self.assertRaisesRegex(ValueError, "only be changed from Settings"):
            self.r.set(nearLondon=False)

    def test_licence_settings_need_authorise(self):
        with self.assertRaisesRegex(ValueError, "only be changed from Settings"):
            self.r.set(licenceClass="full")


class Sim(unittest.TestCase):
    def test_population_depends_only_on_seed_and_band(self):
        a = HamSim({"simSeed": 3, "simRealtime": False, "simHourUtc": 12.0, "vfo": 14_100_000.0}, 1_200_000.0)
        a.open()
        a.set_rx_if(7_100_000.0)
        b = HamSim({"simSeed": 3, "simRealtime": False, "simHourUtc": 12.0, "vfo": 7_100_000.0}, 1_200_000.0)
        b.open()
        self.assertEqual([s.dl for s in a.pops["40m"]], [s.dl for s in b.pops["40m"]])

    def test_time_of_day(self):
        night = HamSim({"simSeed": 3, "simRealtime": False, "simHourUtc": 2.0, "vfo": 1_850_000.0}, 1_200_000.0)
        day = HamSim({"simSeed": 3, "simRealtime": False, "simHourUtc": 13.0, "vfo": 1_850_000.0}, 1_200_000.0)
        night.open()
        day.open()
        self.assertGreater(len(night.pops["160m"]), len(day.pops["160m"]))

    def test_vhf_has_repeaters_with_tones(self):
        s = HamSim({"simSeed": 3, "simRealtime": False, "vfo": 145_500_000.0}, 1_200_000.0)
        s.open()
        reps = s.status()["repeaters"]
        self.assertTrue(reps)
        for r in reps:
            self.assertAlmostEqual(r["in"] - r["out"], -600_000.0)
            self.assertTrue(r["tone"])


if __name__ == "__main__":
    unittest.main()
