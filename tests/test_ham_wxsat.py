"""Radio's weather satellites (ohsradio/wxsat.py, wxsat_tle.py,
wxsat_orbit.py; SERVER-API "Weather satellites"): Meteor-M passes
predicted from a fixed element set at a fixed clock, the plan each one
gets, who the receiver is taken from at AOS and who never, and the
recording itself on the RSPdx-shaped simulator.

Every test brings its own element set (TLE below, Celestrak's of
28/10/2026) and its own clock, so neither the bundled file being
refreshed nor the day the suite runs changes an answer. The passes over
IO75RL that set gives, checked against skyfield to a second and 0.01°
when this was written:

- Meteor-M N2-4 08:12:10Z, highest 2.9° (skip-low)
- Meteor-M N2-3 09:19:21Z-09:34:20Z, highest 41.9° (record)
- Meteor-M N2-4 13:01:36Z, highest 33.7° (record)
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ohscore import sdr, sigmf
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio import wxsat_tle
from ohsradio.radio import Radio

from listen_helpers import ListeningSim
from test_server import SECRET

TLE = """METEOR-M2 3
1 57166U 23091A   26301.59639450 -.00000006  00000+0  16049-4 0  9993
2 57166  98.5923 353.7327 0004774 132.4850 227.6734 14.24055162173505
METEOR-M2 4
1 59051U 24039A   26301.62161587 -.00000010  00000+0  15349-4 0  9993
2 59051  98.7213 259.3532 0007678 137.0518 223.1260 14.22441373138238
"""
# The same two satellites with their epochs a day and a half later
# (26303.1): what a Celestrak fetch brings in the tests that fetch.


def _checksummed(line: str) -> str:
    body = line[:68]
    return body + str(sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in body) % 10)


NEWER = "".join(
    (_checksummed(ln[:18] + "26303.10000000" + ln[32:]) if ln.startswith("1 ") else ln) + "\n"
    for ln in TLE.splitlines())


def utc(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


M23 = "meteor-m2-3-20261029T0919Z"
M24_LOW = "meteor-m2-4-20261029T0812Z"
M24 = "meteor-m2-4-20261029T1301Z"
BEFORE = utc("2026-10-29T08:00:00Z")
IN_PASS = utc("2026-10-29T09:22:00Z")
AFTER = utc("2026-10-29T09:35:00Z")
HOME = 145_500_000.0
MOVED = 89_000_000.0


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def fix(radio, folder: Path, now: float, bundled_text: str = TLE, fetch=None) -> Clock:
    """The radio's weather satellites on a fake clock and a bundle of our own."""
    clock = Clock(now)
    bundled = folder / "bundled.txt"
    bundled.write_text("# fetched 2026-10-28T20:00:00Z celestrak.org GROUP=weather\n" + bundled_text)
    w = radio.wxsat
    w.clock = clock
    w.tle = wxsat_tle.TleStore(folder / "wxsat", lambda: bool(radio.st.get("wxsatOnlineTle", True)), clock=clock,
                               fetch=fetch, bundled=bundled)
    w._cache = None
    return clock


def by_id(view: dict) -> dict:
    return {p["id"]: p for p in view["passes"]}


class Prediction(unittest.TestCase):
    """Passes and their plans, on a radio that is never started."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.radio = Radio({"device": "sim", "audioBackend": "null", "locator": "IO75RL"}, persist=False,
                           data_dir=tmp.name)
        self.clock = fix(self.radio, self.dir, BEFORE)

    def test_the_passes_and_their_plans_for_a_fixed_set_and_clock(self):
        v = self.radio.wxsat.passes_view(12)
        self.assertEqual(v["minElevDeg"], 15)
        self.assertAlmostEqual(v["station"]["lat"], 55.479, places=2)
        self.assertAlmostEqual(v["station"]["lon"], -4.542, places=2)
        p = by_id(v)
        hi = p[M23]
        self.assertEqual((hi["sat"], hi["freqHz"], hi["mode"]), ("Meteor-M N2-3", 137_100_000, "LRPT"))
        self.assertEqual((hi["aos"], hi["los"]), ("2026-10-29T09:19:21Z", "2026-10-29T09:34:20Z"))
        self.assertAlmostEqual(hi["maxElDeg"], 41.9, delta=0.2)
        self.assertEqual((hi["plan"], hi["why"], hi["imageId"]), ("record", None, None))
        self.assertTrue(hi["aos"] < hi["tca"] < hi["los"])
        # The track: every 10 s from AOS, LOS last, rising to the peak and down.
        tr = hi["track"]
        self.assertEqual((tr[0]["t"], tr[-1]["t"]), (hi["aos"], hi["los"]))
        self.assertEqual(utc(tr[1]["t"]) - utc(tr[0]["t"]), 10.0)
        self.assertAlmostEqual(max(x["el"] for x in tr), hi["maxElDeg"], delta=0.3)
        self.assertAlmostEqual(tr[0]["az"], hi["aosAzDeg"], delta=0.2)
        low = p[M24_LOW]
        self.assertEqual(low["plan"], "skip-low")
        self.assertIn("15°", low["why"])
        self.assertEqual((p[M24]["plan"], p[M24]["freqHz"]), ("record", 137_900_000))
        self.assertEqual(self.radio.wxsat.status_view()["state"], "waiting")

        # The minimum is the setting's: at 2° the low pass is recorded too.
        self.radio.set(wxsatMinElevDeg=2)
        self.assertEqual(by_id(self.radio.wxsat.passes_view(12))[M24_LOW]["plan"], "record")

    def test_a_satellite_switched_off_is_skip_disabled_and_says_so(self):
        self.radio.set(wxsatSatellites="meteor-m2-3")
        p = by_id(self.radio.wxsat.passes_view(12))
        self.assertEqual(p[M23]["plan"], "record")
        self.assertEqual(p[M24]["plan"], "skip-disabled")
        self.assertIn("Meteor-M N2-4", p[M24]["why"])

    def test_with_automatic_recording_off_no_pass_is_to_be_recorded(self):
        self.radio.set(wxsatAuto=False)
        v = self.radio.wxsat.passes_view(48)
        self.assertGreater(len(v["passes"]), 10)
        self.assertNotIn("record", {p["plan"] for p in v["passes"]})
        high = [p for p in v["passes"] if p["maxElDeg"] >= 15]
        self.assertTrue(high)
        for p in high:
            self.assertEqual(p["plan"], "skip-disabled")
            self.assertIn("off", p["why"])
        self.assertEqual(self.radio.wxsat.status_view()["state"], "idle")

    def test_a_pass_nobody_recorded_is_missed_once_over(self):
        self.clock.t = AFTER
        self.assertEqual(by_id(self.radio.wxsat.passes_view(2))[M23]["plan"], "missed")

    def test_without_a_locator_there_are_no_passes(self):
        self.radio.set(locator="")
        v = self.radio.wxsat.passes_view(48)
        self.assertEqual((v["station"], v["passes"]), ({"lat": None, "lon": None}, []))

    def test_the_antenna_is_the_operators_2m_one_by_its_label(self):
        class Dev:
            antennas = ["Antenna A", "Antenna B", "Antenna C"]
        w = self.radio.wxsat
        st = self.radio.st             # set as Settings saves them; the stand-in device has no more than inputs
        self.radio.dev = Dev()
        st["soapyAntennaLabels"] = json.dumps({"Antenna A": "Diamond X7000", "Antenna C": "80 m dipole"})
        self.assertEqual(w.antenna(), "Antenna A")
        st["soapyAntennaLabels"] = json.dumps({"Antenna B": "2m yagi", "Antenna C": "80 m dipole"})
        self.assertEqual(w.antenna(), "Antenna B")
        st["soapyAntennaLabels"] = json.dumps({"Antenna C": "80 m dipole"})
        self.assertEqual(w.antenna(), "")                  # none says 2 m: the operator's, unchanged
        # Named in the setting, by label or by input.
        st["wxsatAntenna"] = "80 m dipole"
        self.assertEqual(w.antenna(), "Antenna C")
        st["wxsatAntenna"] = "Antenna B"
        self.assertEqual(w.antenna(), "Antenna B")
        st["wxsatAntenna"] = "Antenna Z"
        self.assertEqual(w.antenna(), "")                  # not an input this device has


class Elements(unittest.TestCase):
    """Where the element sets come from and how old they are."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.radio = Radio({"device": "sim", "audioBackend": "null", "locator": "IO75RL"}, persist=False,
                           data_dir=tmp.name)

    def test_the_bundle_goes_stale_14_days_after_its_epoch(self):
        epoch = wxsat_tle.epoch(TLE.splitlines()[1])          # the older of the two
        clock = fix(self.radio, self.dir, epoch + 13 * 86400)
        t = self.radio.wxsat.passes_view(2)["tle"]
        self.assertEqual((t["source"], t["fetchedUtc"], t["stale"]), ("bundled", "2026-10-28T20:00:00Z", False))
        self.assertAlmostEqual(t["ageDays"], 13.0, delta=0.01)
        clock.t = epoch + 14.5 * 86400
        t = self.radio.wxsat.passes_view(2)["tle"]
        self.assertTrue(t["stale"])
        self.assertAlmostEqual(t["ageDays"], 14.5, delta=0.01)

    def test_celestrak_once_a_day_kept_on_disk_and_silent_offline(self):
        asked = []

        def fetch(url):
            asked.append(url)
            return NEWER.encode()
        clock = fix(self.radio, self.dir, utc("2026-10-30T12:00:00Z"), fetch=fetch)
        store = self.radio.wxsat.tle
        self.assertEqual(store.run_once(), "fetched")
        self.assertEqual(asked, [wxsat_tle.CELESTRAK_URL])
        t = self.radio.wxsat.passes_view(2)["tle"]
        self.assertEqual((t["source"], t["fetchedUtc"], t["stale"]), ("celestrak", "2026-10-30T12:00:00Z", False))
        self.assertAlmostEqual(t["ageDays"], 0.4, delta=0.01)           # from the new epoch, 26303.1
        clock.t += 3600
        self.assertEqual(store.run_once(), "fresh")                      # once a day
        self.assertEqual(len(asked), 1)

        # A day later, offline: no error anywhere, backoff, and the copy
        # on disk is still the one used - by a new store too (a restart).
        def offline(url):
            raise wxsat_tle.FetchFailed("no route")
        clock.t += 86400
        store.fetch = offline
        self.assertEqual(store.run_once(), "failed")
        self.assertEqual(store.run_once(), "backoff")
        again = wxsat_tle.TleStore(self.dir / "wxsat", clock=clock, bundled=self.dir / "bundled.txt")
        sets = again.elements([57166, 59051])
        self.assertEqual({s["source"] for s in sets.values()}, {"celestrak"})

    def test_the_setting_off_means_no_traffic(self):
        asked = []
        fix(self.radio, self.dir, BEFORE, fetch=lambda url: asked.append(url) or NEWER.encode())
        self.radio.set(wxsatOnlineTle=False)
        self.assertEqual(self.radio.wxsat.tle.run_once(), "off")
        self.assertEqual(asked, [])
        self.assertEqual(self.radio.wxsat.passes_view(2)["tle"]["source"], "bundled")

    def test_an_answer_without_our_satellites_changes_nothing(self):
        fix(self.radio, self.dir, BEFORE, fetch=lambda url: b"<html>maintenance</html>")
        self.assertEqual(self.radio.wxsat.tle.run_once(), "failed")
        self.assertEqual(self.radio.wxsat.passes_view(2)["tle"]["source"], "bundled")

    def test_the_operators_own_set_wins_and_is_matched_by_number(self):
        fix(self.radio, self.dir, BEFORE)
        lines = NEWER.splitlines()
        # Only N2-3's, on one line with "|" as a setting must be, named oddly.
        self.radio.set(wxsatTle="|".join(["MY METEOR", lines[1], lines[2]]))
        t = self.radio.wxsat.passes_view(2)["tle"]
        self.assertEqual((t["source"], t["fetchedUtc"]), ("operator", None))
        sets = self.radio.wxsat._sets()
        self.assertEqual((sets[57166]["source"], sets[59051]["source"]), ("operator", "bundled"))
        # A damaged line (its checksum wrong) is not used.
        self.radio.set(wxsatTle="|".join([lines[1][:-1] + "0", lines[2]]))
        self.assertEqual(self.radio.wxsat.passes_view(2)["tle"]["source"], "bundled")


class Carrier:
    """A steady carrier `offset` Hz above Meteor-M N2-3's frequency."""

    def __init__(self, offset: float = 5_000.0, level: float = 0.05):
        self.hz, self.level = 137_100_000.0 + offset, level

    def iq(self, t, rx_if):
        return (self.level * np.exp(2j * np.pi * (self.hz - rx_if) * t)).astype(np.complex64)


class ThreeInputs(ListeningSim):
    """The simulator with an RSPdx's three antenna inputs."""

    antennas = ["Antenna A", "Antenna B", "Antenna C"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.switched = []

    def set_antenna(self, name: str) -> None:
        self.switched.append(name)


def wait(cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class OnTheServer(unittest.TestCase):
    """Radio's real server on the RSPdx-shaped simulator at 2.4 MS/s."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        from ohsradio.devices.simdab import DabEnsemble
        from test_ham_ais import quick_fleet
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
               "locator": "IO75RL", "soapyAntenna": "Antenna C",
               "soapyAntennaLabels": json.dumps({"Antenna A": "Diamond X7000", "Antenna C": "80 m dipole"})}
        self.audio = StreamAudio(realtime=False)
        self.dev = ThreeInputs(dict(cfg), 2_400_000.0, [Carrier(), DabEnsemble("11D", level_db=-30.0),
                                                         quick_fleet()])
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio, device=self.dev)
        self.clock = fix(self.radio, self.dir, BEFORE)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def req(self, method, path, body=None, level="control"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
                   "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
                   "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def plan(self, pid=M23):
        s, v = self.req("GET", "/api/wxsat/passes?hours=6", level="view")
        self.assertEqual(s, 200, v)
        return by_id(v)[pid]

    def owner(self):
        return self.radio.state().get("rxOwner") or {}

    def into_the_pass(self):
        self.clock.t = IN_PASS
        self.radio.wxsat.tick()

    def test_the_routes_answer_to_the_contract(self):
        s, v = self.req("GET", "/api/wxsat/passes?hours=48", level="view")
        self.assertEqual(s, 200)
        self.assertEqual(set(v), {"station", "tle", "minElevDeg", "passes"})
        self.assertEqual(set(v["tle"]), {"source", "fetchedUtc", "ageDays", "stale"})
        self.assertEqual(set(v["passes"][0]), {"id", "sat", "freqHz", "mode", "aos", "tca", "los", "maxElDeg",
                                               "aosAzDeg", "losAzDeg", "track", "plan", "why", "imageId"})
        self.assertEqual(self.req("GET", "/api/wxsat/passes?hours=0", level="view")[0], 400)
        s, st = self.req("GET", "/api/wxsat/status", level="view")
        self.assertEqual(set(st), {"state", "passId", "sat", "freqHz", "az", "el", "snrDb", "lockPct", "lines",
                                   "etaS", "text"})
        self.assertEqual((st["state"], st["passId"], st["snrDb"]), ("waiting", M23, None))
        self.assertEqual(self.req("GET", "/api/wxsat/images", level="view"), (200, []))
        self.assertEqual(self.req("POST", f"/api/wxsat/passes/{M23}/record", level="view")[0], 403)
        self.assertEqual(self.req("POST", "/api/wxsat/passes/nonesuch/record")[0], 404)

    def test_a_pass_is_recorded_as_sigmf_and_the_dial_comes_back_at_los(self):
        self.into_the_pass()
        self.assertEqual(self.plan()["plan"], "recording")
        own = self.owner()
        self.assertEqual((own["by"], own["freqHz"]), ("wxsat", 137_100_000.0))
        self.assertEqual(self.radio.state()["soapyAntenna"], "Antenna A")      # the Diamond X7000
        st = self.req("GET", "/api/wxsat/status", level="view")[1]
        self.assertEqual((st["state"], st["passId"], st["freqHz"]), ("recording", M23, 137_100_000))
        self.assertGreater(st["el"], 0.0)
        # Tuning is refused with the pass's sentence while it records.
        s, e = self.req("POST", "/api/set", {"vfo": 145_400_000.0})
        self.assertEqual(s, 409, e)
        self.assertIn("Meteor-M N2-3", e["error"])
        job = self.radio.wxsat.job
        self.assertTrue(wait(lambda: job["rec"].accepted >= 400_000), "no samples reached the recording")
        # Not given back before LOS.
        self.clock.t = utc("2026-10-29T09:34:00Z")
        self.radio.wxsat.tick()
        self.assertEqual(self.owner().get("by"), "wxsat")
        self.clock.t = AFTER
        self.radio.wxsat.tick()
        self.assertEqual(self.plan()["plan"], "done")
        st = self.radio.state()
        self.assertEqual((st["vfo"], st["mode"], st["rxOwner"], st["soapyAntenna"]),
                         (HOME, "fm", {}, "Antenna C"))

        data = job["rec"].data_path
        meta = json.loads(sigmf.paths(data)[1].read_text())
        g = meta["global"]
        self.assertEqual((g["core:datatype"], g["core:sample_rate"]), ("ci16_le", 800_000.0))
        self.assertEqual(meta["captures"][0]["core:frequency"], 137_100_000.0)
        self.assertEqual(g["openhamshack:service"]["label"], "Meteor-M N2-3")
        wx = g["openhamshack:wxsat"]
        self.assertEqual((wx["passId"], wx["decimation"], wx["deviceRate"]), (M23, 3, 2_400_000.0))
        self.assertIn("137.100MHz-Meteor-M-N2-3-LRPT", data.name)
        self.assertEqual(data.parent, self.radio.recordings_dir())
        # The carrier 5 kHz above the satellite's frequency is 5 kHz above
        # 0 Hz in the file: shifted and decimated, not mirrored or moved.
        raw = np.fromfile(data, "<i2")[: 2 * 262_144].astype(np.float32)
        x = raw[0::2] + 1j * raw[1::2]
        f = np.fft.fftfreq(len(x), 1 / 800_000.0)
        self.assertAlmostEqual(float(f[int(np.argmax(np.abs(np.fft.fft(x))))]), 5_000.0, delta=50.0)

    def test_skipping_a_pass_while_it_records_gives_the_receiver_back(self):
        self.into_the_pass()
        self.assertEqual(self.owner().get("by"), "wxsat")
        s, v = self.req("DELETE", f"/api/wxsat/passes/{M23}/record")
        self.assertEqual(s, 200, v)
        self.assertEqual(v["plan"], "skip-disabled")
        st = self.radio.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["soapyAntenna"]), ({}, HOME, "Antenna C"))
        self.radio.wxsat.tick()                                # and it is not started again
        self.assertEqual(self.owner(), {})

    def test_a_skipped_future_pass_is_left_alone_at_aos(self):
        s, v = self.req("DELETE", f"/api/wxsat/passes/{M23}/record")
        self.assertEqual((s, v["plan"]), (200, "skip-disabled"))
        self.into_the_pass()
        self.assertEqual(self.owner(), {})

    @unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
    def test_dab_playing_at_aos_is_skip_busy_and_untouched(self):
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "dab", "freqHz": 222_064_000.0,
                                                           "params": {"block": "11D", "service": "C221"}})
        self.assertEqual(s, 201, a)
        self.into_the_pass()
        p = self.plan()
        self.assertEqual(p["plan"], "skip-busy")
        self.assertIn("DAB", p["why"])
        self.assertEqual(self.owner()["session"], a["id"])
        self.radio.wxsat.tick()
        self.assertEqual(self.owner()["session"], a["id"])     # still DAB's

    @unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
    def test_forcing_a_pass_ends_the_ship_map_and_records(self):
        s, a = self.req("POST", "/api/ais/session", {"client": "tv-lounge"})
        self.assertEqual(s, 200, a)
        self.assertEqual(self.owner()["by"], "ais")
        self.into_the_pass()
        self.assertEqual(self.plan()["plan"], "skip-busy")
        s, v = self.req("POST", f"/api/wxsat/passes/{M23}/record")
        self.assertEqual(s, 200, v)
        self.assertEqual(v["plan"], "recording")
        self.assertEqual(self.radio.ais.state, "idle")
        self.assertEqual(self.owner()["by"], "wxsat")
        # At LOS the dial is the operator's from before AIS, not AIS's.
        self.clock.t = AFTER
        self.radio.wxsat.tick()
        st = self.radio.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"]), ({}, HOME, "fm"))

    def test_a_recording_running_elsewhere_is_never_preempted(self):
        s, v = self.req("POST", "/api/recordings/start", {"kind": "iq"})
        self.assertEqual(s, 200, v)
        self.addCleanup(lambda: self.req("POST", "/api/recordings/stop", {}))
        self.into_the_pass()
        p = self.plan()
        self.assertEqual(p["plan"], "skip-conflict")
        s, e = self.req("POST", f"/api/wxsat/passes/{M23}/record")
        self.assertEqual(s, 409, e)
        self.assertEqual(e["why"], e["error"])
        self.assertIn("recording", e["why"])
        self.assertEqual(self.owner(), {})
        self.assertTrue(self.radio.rec is not None)            # the other recording carries on


if __name__ == "__main__":
    unittest.main()
