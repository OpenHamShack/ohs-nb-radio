"""Radio's weather-satellite signal measure (ohsradio/wxsat_signal.py; SERVER-API
"Weather satellites", GET api/wxsat/passes/{id}/signal): a power ratio
against the satellite's Doppler-shifted frequency, live while a pass
records and as a timeline of the whole pass after it, kept apart from the
recording; and the past passes GET api/wxsat/passes lists with it.

The pass is test_ham_wxsat.py's: Meteor-M N2-3 over IO75RL, AOS 09:19:21Z,
LOS 09:34:20Z, highest 41.9°, from that file's element set and on its fake
clock; the fixtures are imported from there (only plain helpers, never a
TestCase, which unittest would run twice).

The recordings here are written by hand, as wxsat.py's _start() writes
one (SigMF ci16_le at 800 kS/s - the RSPdx's 2.4 MS/s decimated by 3 -
with `openhamshack:wxsat`), but only a few seconds of it at several points
of the pass, each its own capture after a gap: the timeline must follow
the captures' times rather than the sample count, and a whole pass would
be 3 GB.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from ohscore import sigmf
from ohscore.countries import locator_position
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio import wxsat_orbit, wxsat_signal
from ohsradio.radio import Radio

from test_ham_wxsat import AFTER, BEFORE, IN_PASS, M23, TLE, Carrier, ThreeInputs, by_id, fix, utc, wait
from test_server import SECRET

FS = 800_000.0
NOMINAL = 137_900_000.0
AOS, LOS = utc("2026-10-29T09:19:21Z"), utc("2026-10-29T09:34:20Z")
LAT, LON = locator_position("IO75RL")
M23_TLE = TLE.splitlines()[:3]
RNG = np.random.default_rng(29)
NOISE = 0.01                       # per component: about -40 dBFS, a receiver's floor with the gain set sensibly


def orbit() -> wxsat_orbit.Orbit:
    return wxsat_orbit.Orbit(M23_TLE[1], M23_TLE[2])


def lrpt_like(n: int, level: float) -> np.ndarray:
    """QPSK at 72.7 kBd (800 kS/s / 11), shaped by a windowed sinc to
    about +-60 kHz: flat and ~120 kHz wide like LRPT's channel, not a
    signal anything could demodulate - the measure only needs its power
    where LRPT's would be."""
    sps = 11
    sym = RNG.choice([-1.0, 1.0], size=(n // sps + 2, 2))
    up = np.zeros((n // sps + 2) * sps, np.complex64)
    up[::sps] = sym[:, 0] + 1j * sym[:, 1]
    k = np.arange(-50, 51)
    taps = np.sinc(2 * 60_000.0 / FS * k) * np.hamming(len(k))
    taps *= sps / taps.sum()
    y = np.convolve(up, taps, mode="same")[:n]
    return (y * (level / np.sqrt(np.mean(np.abs(y) ** 2)))).astype(np.complex64)


def noise(n: int) -> np.ndarray:
    return ((RNG.standard_normal(n) + 1j * RNG.standard_normal(n)) * NOISE).astype(np.complex64)


def write_pass(folder: Path, pieces: list[tuple[float, float, bool]], name="pass") -> Path:
    """A SigMF recording of the M23 pass as wxsat.py makes one: `pieces`
    are (UTC start, seconds, with the satellite), each its own capture
    after a gap. The satellite is followed by its real Doppler shift
    (Orbit.doppler_hz), so a timeline that centred its band anywhere else
    would miss it."""
    folder.mkdir(parents=True, exist_ok=True)
    data, meta = sigmf.paths(folder / name)
    orb = orbit()
    caps, start = [], 0
    with open(data, "wb") as f:
        for t0, secs, sat in pieces:
            n = int(secs * FS)
            x = noise(n)
            if sat:
                # Linear between the ends: the shift moves at most ~20 Hz/s.
                d0, d1 = (orb.doppler_hz(t, LAT, LON, NOMINAL) for t in (t0, t0 + secs))
                hz = np.linspace(d0, d1, n)
                x += lrpt_like(n, 0.03) * np.exp(2j * np.pi * np.cumsum(hz) / FS).astype(np.complex64)
            f.write(sigmf.to_ci16(x)[0])
            caps.append({"core:sample_start": start, "core:frequency": NOMINAL,
                         "core:datetime": sigmf.iso_utc(t0), "openhamshack:utc": round(t0, 6)})
            start += n
    g = {"core:datatype": "ci16_le", "core:sample_rate": FS, "core:version": "1.0.0",
         "openhamshack:wxsat": {"passId": M23, "satellite": "Meteor-M N2-3", "norad": 57166, "nominalHz": NOMINAL,
                                "aos": "2026-10-29T09:19:21Z", "los": "2026-10-29T09:34:20Z", "maxElDeg": 41.9,
                                "tle": M23_TLE, "tleSource": "bundled", "deviceRate": 2_400_000.0,
                                "decimation": 3}}
    meta.write_text(json.dumps({"global": g, "captures": caps, "annotations": []}))
    return data


# Eight two-second looks across the pass: the first four (before TCA,
# 09:26:53) noise alone, the last four with the satellite in.
PIECES = [(AOS + 30.0 + 100.0 * i, 2.0, i >= 4) for i in range(8)]


class Measure(unittest.TestCase):
    """measure() on its own, on one second of synthetic IQ."""

    def test_noise_reads_0_db_the_satellite_well_above_and_only_where_it_is(self):
        n = int(FS)
        off = 2_900.0                                     # a Doppler shift near AOS
        quiet, quiet_floor = wxsat_signal.measure(noise(n), FS, off)
        self.assertLess(abs(quiet), 1.0)                  # a second of noise: within a dB of 0
        t = np.arange(n) / FS
        x = noise(n) + lrpt_like(n, 0.03) * np.exp(2j * np.pi * off * t).astype(np.complex64)
        heard, floor = wxsat_signal.measure(x, FS, off)
        self.assertGreater(heard, quiet + 10.0)
        # The floor is the noise's, signal or not: per hertz, from the bins beside the band.
        self.assertAlmostEqual(floor, quiet_floor, delta=1.0)
        # Measured 200 kHz away (> BAND_HALF_HZ) the band holds only noise
        # again: the band is where it is said to be, not the total power.
        away, _floor = wxsat_signal.measure(x, FS, off + 200_000.0)
        self.assertLess(abs(away - quiet), 2.0)

    def test_per_hz_so_the_rate_does_not_move_the_noise(self):
        # The same noise density at the lowest rate wxsat.py records at
        # (MIN_RATE, where the guard still leaves bins) and at 800 kS/s.
        _s, at_800 = wxsat_signal.measure(noise(int(FS)), FS, 0.0)
        slow = noise(250_000) * np.float32(np.sqrt(250_000.0 / FS))
        snr, at_250 = wxsat_signal.measure(slow, 250_000.0, 0.0)
        self.assertLess(abs(snr), 1.0)
        self.assertAlmostEqual(at_250, at_800, delta=0.5)

    def test_too_few_samples_is_none_not_a_crash(self):
        self.assertEqual(wxsat_signal.measure(noise(100), FS, 0.0), (None, None))
        self.assertEqual(wxsat_signal.measure(np.zeros(8192, np.complex64), FS, 0.0), (None, None))
        snr, _n = wxsat_signal.measure(noise(1000), FS, 0.0)       # a short last second: 512 points
        self.assertIsNotNone(snr)


class Doppler(unittest.TestCase):
    """Orbit.doppler_hz: a sanity check on the pass, not a certification."""

    def test_the_shift_falls_through_zero_at_closest_approach(self):
        o = orbit()
        tca = utc("2026-10-29T09:26:53Z")
        rise, set_ = (o.doppler_hz(t, LAT, LON, NOMINAL) for t in (AOS, LOS))
        self.assertTrue(2_000.0 < rise < 3_500.0, rise)          # coming closer: up, a few kHz at 137 MHz
        self.assertTrue(-3_500.0 < set_ < -2_000.0, set_)
        self.assertAlmostEqual(rise, -set_, delta=300.0)        # near-overhead: about symmetric
        self.assertLess(abs(o.doppler_hz(tca, LAT, LON, NOMINAL)), 100.0)


class Timeline(unittest.TestCase):
    """timeline() from a recording and nothing else; save(), load(), the worker."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_a_pass_second_by_second_where_the_satellite_was(self):
        data = write_pass(self.dir / "rec", PIECES)
        tl = wxsat_signal.timeline({"passId": M23, "data": data, "lat": LAT, "lon": LON})
        self.assertEqual((tl["passId"], tl["sat"], tl["freqHz"]), (M23, "Meteor-M N2-3", 137_900_000))
        s = tl["samples"]
        self.assertEqual(len(s), 16)                      # two seconds in each of eight captures
        self.assertEqual(set(s[0]), {"t", "az", "el", "snrDb"})
        quiet = [x["snrDb"] for x in s[:8]]
        heard = [x["snrDb"] for x in s[8:]]
        for v in quiet:
            self.assertTrue(-5.0 < v < 5.0, quiet)
        self.assertGreater(min(heard), max(quiet) + 10.0, (quiet, heard))
        self.assertIsInstance(tl["noiseFloorDb"], float)
        # Each second at its own time, across the gaps: the middle of it.
        self.assertEqual(s[0]["t"], "2026-10-29T09:19:51.5Z")
        self.assertEqual(s[-1]["t"], "2026-10-29T09:31:32.5Z")        # AOS + 730 s, its second second
        # The timeline's propagation agrees with passes_view's track (every
        # 10 s, interpolated here), from the same element set.
        track = wxsat_orbit.track(orbit(), LAT, LON, AOS, LOS, 10.0)
        tt = [t for t, _az, _el in track]
        az = np.degrees(np.unwrap(np.radians([a for _t, a, _e in track])))
        el = [e for _t, _a, e in track]
        for x in s:
            t = utc(x["t"])
            self.assertAlmostEqual(x["el"], float(np.interp(t, tt, el)), delta=1.0)
            self.assertAlmostEqual(x["az"], float(np.interp(t, tt, az)) % 360.0, delta=1.0)

    def test_kept_after_the_recording_is_deleted(self):
        data = write_pass(self.dir / "rec", PIECES[3:5])
        folder = self.dir / "signal"
        said = []
        w = wxsat_signal.SignalWorker(folder, lambda *a: said.append(a))
        w.submit({"passId": M23, "data": data, "lat": LAT, "lon": LON})
        self.assertTrue(wait(lambda: said, 60.0))
        self.assertEqual(said, [(M23, True, None)])
        made = wxsat_signal.load(folder, M23)
        self.assertEqual(len(made["samples"]), 4)
        for p in sigmf.paths(data):
            p.unlink()
        self.assertEqual(wxsat_signal.load(folder, M23), made)
        self.assertTrue(wxsat_signal.has(folder, M23))
        # Kept 30 days by its own clock, not the recording's or the marks'.
        now = time.time()
        wxsat_signal.prune(folder, now + 29 * 86_400.0)
        self.assertTrue(wxsat_signal.has(folder, M23))
        wxsat_signal.prune(folder, now + 31 * 86_400.0)
        self.assertFalse(wxsat_signal.has(folder, M23))

    def test_a_recording_without_its_element_set_fails_the_job_not_the_worker(self):
        data = write_pass(self.dir / "rec", PIECES[:1])
        meta = sigmf.paths(data)[1]
        m = json.loads(meta.read_text())
        del m["global"]["openhamshack:wxsat"]["tle"]
        meta.write_text(json.dumps(m))
        good = write_pass(self.dir / "rec", PIECES[:1], name="good")
        said = []
        w = wxsat_signal.SignalWorker(self.dir / "signal", lambda *a: said.append(a))
        w.submit({"passId": "bad", "data": data, "lat": LAT, "lon": LON})
        w.submit({"passId": M23, "data": good, "lat": LAT, "lon": LON})
        self.assertTrue(wait(lambda: len(said) == 2, 60.0))
        self.assertEqual((said[0][:2], said[1]), (("bad", False), (M23, True, None)))
        self.assertIsNone(wxsat_signal.load(self.dir / "signal", "bad"))
        self.assertIsNone(wxsat_signal.load(self.dir / "signal", "../passes"))   # never a path


class PastPasses(unittest.TestCase):
    """GET api/wxsat/passes's `past` and `signal`, and the startup backfill,
    on a radio that is never started."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.radio = self.a_radio()

    def a_radio(self):
        radio = Radio({"device": "sim", "audioBackend": "null", "locator": "IO75RL"}, persist=False,
                      data_dir=str(self.dir))
        self.clock = fix(radio, self.dir, AFTER)
        return radio

    def recorded(self) -> Path:
        """M23 as a finished pass leaves it: its mark `done` with its file."""
        data = write_pass(self.radio.recordings_dir(), PIECES[4:5], name="m23")
        w = self.radio.wxsat
        w.marks[M23] = {"sat": "meteor-m2-3", "aos": AOS, "los": LOS, "plan": "done", "why": None,
                        "file": data.name, "seconds": 2.0}
        w._save_marks()
        return data

    def test_finished_passes_are_listed_as_far_back_as_asked_and_after_a_restart(self):
        self.recorded()
        wxsat_signal.save(self.radio.wxsat.signal_dir, M23, {"passId": M23, "samples": []})
        # Ten days on: past the week marks used to be kept, inside the 30 days a client may ask for.
        self.clock.t = AFTER + 10 * 86_400.0
        self.radio.wxsat._save_marks()
        self.radio = self.a_radio()                          # a restart: only what is on disk
        self.clock.t = AFTER + 10 * 86_400.0
        w = self.radio.wxsat
        self.assertNotIn(M23, by_id(w.passes_view(2)))       # the default, a day back
        p = by_id(w.passes_view(2, 24 * 11))
        self.assertEqual((p[M23]["plan"], p[M23]["signal"]), ("done", f"api/wxsat/passes/{M23}/signal"))
        # The others of that day are there with what became of them, signal null.
        self.assertEqual(by_id(w.passes_view(2, 24 * 11))["meteor-m2-4-20261029T1301Z"]["plan"], "missed")
        self.assertIsNone(p["meteor-m2-4-20261029T1301Z"]["signal"])
        self.assertTrue(all(utc(x["los"]) > self.clock.t - 11 * 86_400 for x in p.values()))

    def test_the_backfill_makes_a_timeline_for_a_recording_that_has_none(self):
        data = self.recorded()
        w = self.radio.wxsat
        self.assertIsNone(by_id(w.passes_view(2))[M23]["signal"])
        w.backfill_signal()
        self.assertTrue(wait(lambda: wxsat_signal.has(w.signal_dir, M23) and w.signal.idle(), 60.0))
        v = w.signal_view(M23)
        self.assertEqual(len(v["samples"]), 2)
        self.assertGreater(v["samples"][0]["snrDb"], 10.0)
        self.assertEqual(by_id(w.passes_view(2))[M23]["signal"], f"api/wxsat/passes/{M23}/signal")
        # Again (the next startup): nothing to do - and a pass whose recording
        # is gone is skipped, not failed.
        made = (w.signal_dir / f"{M23}.json").stat().st_mtime_ns
        data.unlink()
        w.backfill_signal()
        self.assertTrue(wait(w.signal.idle))
        self.assertEqual((w.signal_dir / f"{M23}.json").stat().st_mtime_ns, made)


class Live(unittest.TestCase):
    """The meter while a pass records, and the routes, on Radio's real server
    and the RSPdx-shaped simulator (test_ham_wxsat.OnTheServer's)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": 145_500_000.0,
               "mode": "fm", "locator": "IO75RL"}
        self.audio = StreamAudio(realtime=False)
        self.dev = ThreeInputs(dict(cfg), 2_400_000.0, [Carrier()])
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio, device=self.dev)
        self.clock = fix(self.radio, self.dir, BEFORE)
        self.radio.wxsat.decoder.binary = ""
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        self.port = self.srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def req(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("GET", path, None, {shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "brian",
                                      "X-OpenHamShack-Level": "view", "X-OpenHamShack-Device": "dev_TEST",
                                      "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def test_snr_is_live_while_recording_and_the_timeline_follows_at_los(self):
        w = self.radio.wxsat
        self.assertIsNone(w.status_view()["snrDb"])            # waiting: nothing to measure
        self.clock.t = IN_PASS
        w.tick()
        job = w.job
        self.assertIsNotNone(job)
        # A second and more recorded: the meter has had its first second.
        self.assertTrue(wait(lambda: job["rec"].accepted >= 2 * 800_000 and w.status_view()["snrDb"] is not None),
                        "no live snrDb")
        s, st = self.req("/api/wxsat/status")
        self.assertEqual((s, st["state"]), (200, "recording"))
        # The simulator's carrier, 5 kHz up, is inside the band: well above nothing.
        self.assertGreater(st["snrDb"], 3.0)
        self.assertEqual((st["lockPct"], st["lines"]), (None, None))
        self.assertEqual(self.req(f"/api/wxsat/passes/{M23}/signal"), (404, {
            "error": "There is no signal timeline for that pass", "code": "no_signal"}))
        self.clock.t = AFTER
        w.tick()
        self.assertTrue(wait(lambda: wxsat_signal.has(w.signal_dir, M23) and w.signal.idle(), 60.0))
        s, tl = self.req(f"/api/wxsat/passes/{M23}/signal")
        self.assertEqual((s, tl["passId"], tl["freqHz"]), (200, M23, 137_900_000))
        self.assertTrue(tl["samples"])
        s, v = self.req("/api/wxsat/passes?hours=2&past=2")
        self.assertEqual(by_id(v)[M23]["signal"], f"api/wxsat/passes/{M23}/signal")

    def test_past_is_from_1_to_720_hours(self):
        self.assertEqual(self.req("/api/wxsat/passes?past=720")[0], 200)
        for bad in ("0", "721", "x"):
            s, e = self.req(f"/api/wxsat/passes?past={bad}")
            self.assertEqual((s, e["code"]), (400, "bad_params"))
        self.assertEqual(self.req("/api/wxsat/passes/nonesuch/record")[0], 404)


if __name__ == "__main__":
    unittest.main()
