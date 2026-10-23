"""Radio's weekly band scan (ohsradio/bandscan.py), on the RSPdx-shaped
simulator with shack_sdr's FM stereo and RDS transmitter on Band II
(simfm.py) and its DAB ensemble on 11D (simdab.py). The scanner's clock is
a fake one: nothing here waits for a night to come.

- **When:** the first tick in the hour after scanHour, once a night, for
  a band whose list is more than a week old (the same night a week later
  counts); never outside that hour; off with scanAuto.
- **Idle:** each busy condition skips the night with its reason as the
  band's status, and the next night tries again.
- **The scan:** FM merged by PI (the strongest frequency best, the other
  an alternative; a station without RDS by its frequency), DAB per
  ensemble with its services; kept on disk; `stationsAt` and a `stations`
  item say so.
- **Gives way and puts back:** a set(), a listener, a key-up, a decoder,
  a recording or a stop in the middle ends the scan at once with every
  setting kept put back exactly (the receiver's centre too), before the
  caller's own change; the old list stays.
- **Over the API:** api/fm/stations, api/dab/stations, POST api/scan and
  its refusals, the `stations` event and `bandScan` progress; QO-100 NB has
  no lists.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from ohscore import sdr
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import bandscan, server as ham_server
from ohsradio.bandscan import BandScanner, fm_hops, fm_reach, merge_fm
from ohsradio.radio import Radio

from ham_helpers import close, pump
from listen_helpers import ListeningSim, make_listener
import test_server
from test_server import SECRET

HOME = 145_500_000.0
UTC = timezone.utc
# A fixed week: Monday 2 November 2026, local time = UTC.
DAY0 = datetime(2026, 11, 2, tzinfo=UTC).timestamp()


def at(day: int, hour: float) -> float:
    return DAY0 + day * 86400 + hour * 3600


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def on_air(dev):
    from ohsradio.devices.simdab import DabEnsemble
    from ohsradio.devices.simfm import BAND, FmBand
    dev.fm = FmBand(list(BAND))
    dev.dab = DabEnsemble("11D", level_db=-30.0)


def scanned(r, timeout=300.0):
    """Wait for the scan's worker to end (the simulator runs faster than real time)."""
    sc = r.bandscan
    pump(r, timeout, until=lambda: not (sc.thread is not None and sc.thread.is_alive()))
    return not (sc.thread is not None and sc.thread.is_alive())


class Geometry(unittest.TestCase):
    """The hop plan and the merge, without a radio."""

    def test_every_channel_once_within_reach_dc_between_channels(self):
        for fs, hops in ((2_400_000.0, 11), (2_048_000.0, 13), (1_200_000.0, 26)):
            plan = fm_hops(fs)
            self.assertEqual(len(plan), hops, fs)
            chans = [g for _c, run in plan for g in run]
            self.assertEqual(sorted(chans), list(range(87_500_000, 108_000_001, 100_000)))
            for c, run in plan:
                self.assertEqual(c % 100_000, 50_000)             # DC half-way between two channels
                self.assertTrue(all(abs(g - c) <= fm_reach(fs) for g in run), (fs, c))
        self.assertEqual(fm_reach(2_400_000.0), 950_000.0)

    def test_merged_by_pi_strongest_best(self):
        found = [
            {"hz": 91_300_000, "levelDb": -47.2, "stereo": True, "pi": "C201", "ps": "SIM ONE ", "pty": None,
             "ptyName": None, "rt": None},
            {"hz": 88_600_000, "levelDb": -38.04, "stereo": True, "pi": "C201", "ps": "SIM ONE ", "pty": 10,
             "ptyName": "Pop music", "rt": None},
            {"hz": 97_700_000, "levelDb": -46.0, "stereo": True, "pi": None, "ps": None, "pty": None,
             "ptyName": None, "rt": None},
            {"hz": 89_900_000, "levelDb": -50.0, "stereo": False, "pi": "C201", "ps": None, "pty": None,
             "ptyName": None, "rt": "Now playing"},
        ]
        got = merge_fm(found)
        self.assertEqual(got, [
            {"pi": "C201", "ps": "SIM ONE", "pty": 10, "ptyName": "Pop music", "rt": "Now playing",
             "best": {"hz": 88_600_000, "level": -38.0, "stereo": True},
             "alts": [{"hz": 91_300_000, "level": -47.2, "stereo": True},
                      {"hz": 89_900_000, "level": -50.0, "stereo": False}]},
            {"pi": None, "ps": None, "pty": None, "ptyName": None, "rt": None,
             "best": {"hz": 97_700_000, "level": -46.0, "stereo": True}, "alts": []}])


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class When(unittest.TestCase):
    """The nightly attempt, the week and the idle rules, with the scan
    itself replaced by a note of what would have been scanned."""

    def setUp(self):
        r, _audio, dev = make_listener([], receive_only=False, vfo=HOME, mode="fm")
        self.addCleanup(close, r)
        self.r = r
        self.clock = Clock(at(0, 12))
        r.bandscan.clock, r.bandscan.tz = self.clock, UTC
        self.started = []
        r.bandscan._start = lambda bands: self.started.append(bands)
        r.start()

    def night(self, day, minute=0.1):
        self.clock.t = at(day, 3 + minute / 60)
        self.r.bandscan.tick()

    def test_the_first_night_scans_both_once(self):
        sc = self.r.bandscan
        self.assertEqual(sc.view("fm")["nextDue"], "2026-11-03T03:00:00Z")
        self.clock.t = at(1, 2.99)
        sc.tick()
        self.assertEqual(self.started, [])
        self.night(1)
        self.assertEqual(self.started, [("fm", "dab")])
        self.night(1, minute=30)                         # the same night: once
        self.assertEqual(len(self.started), 1)
        self.clock.t = at(2, 4.5)                        # outside the hour
        sc.tick()
        self.assertEqual(len(self.started), 1)

    def test_a_week_is_the_same_night_a_week_later(self):
        sc = self.r.bandscan
        for b in bandscan.BANDS:
            sc.records[b]["scannedAt"] = at(0, 3 + 1.5 / 60)     # finished at 03:01:30
        self.assertEqual(sc.view("fm")["nextDue"], "2026-11-09T03:00:00Z")
        for day in range(1, 7):
            self.night(day)
        self.assertEqual(self.started, [])
        self.night(7)
        self.assertEqual(self.started, [("fm", "dab")])

    def test_only_the_band_that_is_due(self):
        sc = self.r.bandscan
        sc.records["fm"]["scannedAt"] = at(0, 3)
        self.night(2)
        self.assertEqual(self.started, [("dab",)])

    def test_off_means_off(self):
        self.r.set(scanAuto=False)
        self.night(1)
        self.assertEqual(self.started, [])
        self.assertIsNone(self.r.bandscan.view("fm")["nextDue"])

    def busy_then_idle(self, make_busy, make_idle, says, day=1):
        """Busy: the night is skipped with the reason; the next night,
        idle, it runs."""
        self.clock.t = at(day - 1, 12)
        make_busy()
        self.night(day)
        self.assertEqual(self.started, [], says)
        v = self.r.bandscan.view("fm")
        self.assertEqual((v["status"], v["statusText"]), ("busy", says))
        self.assertEqual(v["nextDue"], datetime.fromtimestamp(at(day + 1, 3), UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.clock.t = at(day, 12)
        make_idle()
        self.night(day + 1)
        self.assertEqual(self.started, [("fm", "dab")], says)

    def test_a_listener_waits_for_the_next_night(self):
        n = [1]
        self.r.bandscan.listeners = lambda: n[0]
        self.busy_then_idle(lambda: None, lambda: n.__setitem__(0, 0), "Someone is listening")

    def test_someone_tuning_lately_waits(self):
        def tune():
            self.clock.t = at(1, 2.9)                    # six minutes before the hour
            self.r.set(vfo=HOME + 25_000.0)
        self.busy_then_idle(tune, lambda: None, "The radio was used in the last 30 minutes")

    def test_transmitting_waits(self):
        self.r.set(volume=0.5)
        def unkey():
            self.r.ptt(False)
            pump(self.r, 10, until=self.r.tx_idle)
        self.busy_then_idle(lambda: self.r.ptt(True), unkey, "Transmitting")

    def test_an_iq_recording_waits(self):
        self.busy_then_idle(lambda: self.r.start_recording(), self.r.stop_recording, "An IQ recording is being made")

    def test_a_decoder_session_waits(self):
        made = []
        self.busy_then_idle(lambda: made.append(self.r.decoders.start("rtty", HOME + 10_000.0, {})),
                            lambda: self.r.decoders.stop(made[0]["id"]), "A decoder is running")

    def test_a_receiver_someone_holds_waits(self):
        made = []
        says = ("The receiver is in use: The receiver is playing DAB from block 11D: stop the DAB station to tune "
                "or change mode")
        self.busy_then_idle(lambda: made.append(self.r.decoders.start("dab", None, {"block": "11D", "service": ""})),
                            lambda: self.r.decoders.stop(made[0]["id"]), says)

    def test_the_cw_skimmer_waits(self):
        self.r.CWSKIM_MODE = "thread"
        self.busy_then_idle(lambda: self.r.set(cwSkim=True), lambda: self.r.set(cwSkim=False),
                            "The CW skimmer is running")

    def test_a_broadcast_station_playing_on_the_desktop_waits(self):
        self.busy_then_idle(lambda: self.r.set(mode="wfm", vfo=97_700_000.0), lambda: self.r.set(mute=True),
                            "A station is playing")

    def test_a_stopped_radio_is_not_scanned(self):
        self.r.stop()
        self.r.bandscan.tick()
        self.night(1)
        self.assertEqual(self.started, [])
        self.assertEqual(self.r.bandscan.view("fm")["statusText"], "The radio is not running")


KEPT = ("vfo", "mode", "rptOffsetHz", "rptShift", "rptReverse", "rit", "ritOn", "rxGainMode", "rxGain", "sdrplayLna",
        "soapyAntenna", "sampleRate", "wfmDeemphasis")


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class TheScan(unittest.TestCase):
    def setUp(self):
        r, audio, dev = make_listener([], receive_only=False, vfo=145_412_500.0, mode="fm", rptShift="minus",
                                      rit=120.0, ritOn=True, rxGainMode="manual", rxGain=33.0, sdrplayLna=7,
                                      wfmDeemphasis=75.0)
        on_air(dev)
        self.addCleanup(close, r)
        self.r = r
        r.start()
        pump(r, 5, until=r._rx_settled)
        self.before = self.kept()
        self.centre = r.centre

    def kept(self):
        st = self.r.state()
        return {k: st[k] for k in KEPT}

    def test_both_bands_found_merged_kept_and_everything_put_back(self):
        r = self.r
        sc = r.bandscan
        sc.fm_lo, sc.fm_hi = 87_500_000, 95_000_000
        sc.dab_blocks = ["11C", "11D"]
        feed = r.subscribe("stations", 16)
        state = r.subscribe("state", 20_000)
        self.assertEqual(sc.scan_now("both")["bands"], ["fm", "dab"])
        self.assertEqual(r.state()["rxOwner"]["by"], "scan")
        self.assertTrue(scanned(r))
        fm = sc.view("fm")
        self.assertEqual(fm["status"], "ok")
        got = {(p["pi"], p["best"]["hz"]): p for p in fm["stations"]}
        self.assertEqual(sorted(got), [("C201", 88_600_000), ("C3B4", 93_500_000)])
        one = got[("C201", 88_600_000)]
        self.assertEqual((one["ps"], one["pty"], one["ptyName"], one["best"]["stereo"]),
                         ("SIM ONE", 10, "Pop music", True))
        self.assertEqual([a["hz"] for a in one["alts"]], [91_300_000])
        self.assertFalse(got[("C3B4", 93_500_000)]["best"]["stereo"])
        dab = sc.view("dab")
        self.assertEqual(dab["ensembles"], [{"block": "11D", "freqHz": 222_064_000, "id": "C1CE",
                                             "label": "Shack Test Mux", "services": [
                                                 {"sid": "C221", "label": "Shack MP2 Tone", "kind": "dab",
                                                  "bitrate": 128},
                                                 {"sid": "C3A7", "label": "Shack DAB+ Data", "kind": "dab+",
                                                  "bitrate": 64}]}])
        # Everything as it was, the receiver's centre too.
        pump(r, 5, until=lambda: r.centre == self.centre)
        self.assertEqual(self.kept(), self.before)
        self.assertEqual(r.centre, self.centre)
        self.assertEqual((r.state()["rxOwner"], r.state()["bandScan"]), ({}, {}))
        # Said: an event per band, stationsAt, and progress on the way.
        items = pump(r, 1, feeds=[feed, state])
        self.assertEqual([(i["band"], i["count"]) for i in items["stations"]], [("fm", 2), ("dab", 1)])
        self.assertEqual(r.state()["stationsAt"], {"fm": fm["scannedAt"], "dab": dab["scannedAt"]})
        progress = [c["changes"]["bandScan"] for c in items["state"] if c["changes"].get("bandScan")]
        self.assertEqual({p["band"] for p in progress}, {"fm", "dab"})
        self.assertIn("listening", {p["phase"] for p in progress})
        self.assertTrue(any(p["text"].startswith("DAB: block 11D") for p in progress))
        # Kept on disk: a new scanner reads the same lists.
        again = BandScanner(r, clock=sc.clock)
        self.assertEqual(again.view("fm")["stations"], fm["stations"])
        self.assertEqual(again.view("dab")["ensembles"], dab["ensembles"])

    def in_the_middle(self):
        """Scan FM and return once the second hop has begun."""
        r = self.r
        sc = r.bandscan
        sc.records["fm"]["stations"] = [{"pi": "OLD", "best": {"hz": 1}}]
        first = fm_hops(r.geo.fs)[0][0]
        sc.scan_now("fm")
        pump(r, 60, until=lambda: (r.state()["bandScan"] or {}).get("freqHz") not in (None, first))
        self.assertGreater((r.state()["bandScan"] or {}).get("percent", 0), 0)
        self.assertEqual(r.state()["rxOwner"]["by"], "scan")

    def given_back(self, why):
        r = self.r
        self.assertTrue(scanned(r, 30))
        v = r.bandscan.view("fm")
        self.assertEqual(v["status"], "aborted")
        self.assertEqual(v["statusText"], f"Stopped: the radio was wanted ({why})")
        self.assertEqual(v["stations"], [{"pi": "OLD", "best": {"hz": 1}}])       # the old list stays
        self.assertEqual(r.state()["rxOwner"], {})

    def test_a_tune_takes_it_back_and_applies_after_the_restore(self):
        self.in_the_middle()
        self.r.set(rxGain=20.0)
        # At once, on this thread: the hold is gone before set() returns.
        self.assertEqual(self.r.state()["rxOwner"], {})
        self.given_back("set")
        self.assertEqual(self.kept(), dict(self.before, rxGain=20.0))
        pump(self.r, 5, until=lambda: self.r.centre == self.centre)
        self.assertEqual(self.r.centre, self.centre)

    def test_a_listener_or_anyone_takes_it_back_exactly(self):
        for what in ("listener", "decoder", "playback"):
            with self.subTest(what=what):
                self.in_the_middle()
                self.r.client_activity(what)
                self.given_back(what)
                self.assertEqual(self.kept(), self.before)
                pump(self.r, 5, until=lambda: self.r.centre == self.centre)
                self.assertEqual(self.r.centre, self.centre)

    def test_a_key_up_takes_it_back_and_is_judged_at_home(self):
        self.in_the_middle()
        self.r.set(rptShift="simplex", ritOn=False)  # the simplex channel: FM keys there with a Full licence
        self.given_back("set")
        self.r.ptt(True)
        self.assertTrue(self.r.state()["keyed"])
        self.assertEqual(self.r.state()["txDial"], 145_412_500.0)
        self.r.ptt(False)

    def test_stopping_the_radio_puts_it_back_first(self):
        self.in_the_middle()
        self.r.stop()
        self.given_back("stop")
        self.assertEqual(self.kept(), self.before)
        self.assertEqual({k: self.r.cfg[k] for k in ("vfo", "mode", "rxGain")},
                         {k: self.before[k] for k in ("vfo", "mode", "rxGain")})

    def test_the_scan_never_keys(self):
        r = self.r
        sc = r.bandscan
        sc.fm_lo, sc.fm_hi = 97_000_000, 99_000_000
        sc.dab_blocks = ["11D"]
        keyed = []
        r.subscribe("state", 20_000)
        feed = r.subscribe("state", 20_000)
        sc.scan_now("both")
        # A hold that gives way refuses nothing, and the dial it leaves alone
        # is what the guard judges: FM simplex at home keys for a Full licence.
        self.assertEqual(r.state()["vfo"], 145_412_500.0)
        self.assertEqual(r.state()["txBlocked"], "")
        self.assertTrue(scanned(r))
        for c in pump(r, 0.5, feeds=[feed])["state"]:
            if c["changes"].get("keyed"):
                keyed.append(c)
        self.assertEqual(keyed, [])
        self.assertEqual(r.dev.drive, 0.0)


class Refusals(unittest.TestCase):
    @unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
    def test_scan_now_says_why_not(self):
        r, _audio, _dev = make_listener([], vfo=HOME, mode="fm")
        self.addCleanup(close, r)
        sc = r.bandscan
        with self.assertRaises(bandscan.Refused) as e:
            sc.scan_now("fm")
        self.assertEqual((e.exception.code, str(e.exception)), ("not_running", "Start the radio before scanning"))
        r.start()
        with self.assertRaises(bandscan.Refused) as e:
            sc.scan_now("am")
        self.assertEqual(e.exception.code, "bad_params")
        r.start_recording()
        with self.assertRaises(bandscan.Refused) as e:
            sc.scan_now("both")
        self.assertEqual((e.exception.code, str(e.exception)),
                         ("receiver_busy", "Not scanning now: An IQ recording is being made"))
        r.stop_recording()

    def test_a_receiver_too_slow_for_dab_scans_fm_alone(self):
        if not sdr.available():
            self.skipTest("no shack_sdr for this machine")
        r, _audio, _dev = make_listener([], fs=1_200_000.0, vfo=HOME, mode="fm")
        self.addCleanup(close, r)
        r.start()
        sc = r.bandscan
        self.assertIn("DAB needs the receiver to run at 2.048 MS/s or more", sc.unsupported("dab"))
        with self.assertRaises(bandscan.Refused) as e:
            sc.scan_now("dab")
        self.assertEqual(e.exception.code, "unsupported")
        sc.fm_lo, sc.fm_hi = 97_000_000, 98_000_000
        self.assertEqual(sc.scan_now("both")["bands"], ["fm"])
        self.assertTrue(scanned(r))


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class OverTheApi(unittest.TestCase):
    ws = test_server.Streams.ws
    frame = staticmethod(test_server.Streams.frame)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm"}
        self.audio = StreamAudio(realtime=False)
        dev = ListeningSim(dict(cfg), 2_400_000.0, [])
        on_air(dev)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio, device=dev)
        self.radio.bandscan.fm_lo, self.radio.bandscan.fm_hi = 88_000_000, 90_000_000
        self.radio.bandscan.dab_blocks = ["11D"]
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def req(self, method, path, body=None, level="control"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
                   "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
                   "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def test_lists_scan_now_and_the_event(self):
        s, a = self.req("GET", "/api/fm/stations", level="view")
        self.assertEqual((s, a["status"], a["statusText"], a["scannedAt"], a["stations"]),
                         (200, "never", "Not scanned yet", None, []))
        self.assertIsNotNone(a["nextDue"])
        s, a = self.req("GET", "/api/dab/stations", level="view")
        self.assertEqual((s, a["ensembles"]), (200, []))
        sock, f = self.ws("/api/events?kinds=stations")
        self.assertEqual(json.loads(self.frame(f)[1])["kind"], "hello")
        s, a = self.req("POST", "/api/scan", {"band": "both"}, level="view")
        self.assertEqual((s, a["code"]), (403, "level_too_low"))
        s, a = self.req("POST", "/api/scan", {"band": "both"})
        self.assertEqual((s, a["bands"]), (202, ["fm", "dab"]), a)
        s, a = self.req("POST", "/api/scan", {"band": "fm"})
        self.assertEqual((s, a["code"], a["error"]), (409, "receiver_busy",
                                                     "Not scanning now: A band scan is running already"))
        self.assertEqual(self.req("GET", "/api/fm/stations", level="view")[1]["status"], "scanning")
        sock.settimeout(300)            # the scan's length, on however loaded a machine
        events = [json.loads(self.frame(f)[1]) for _ in range(2)]
        sock.close()
        self.assertEqual([(e["kind"], e["band"], e["count"]) for e in events], [("stations", "fm", 1),
                                                                                ("stations", "dab", 1)])
        self.assertTrue(scanned(self.radio))
        s, a = self.req("GET", "/api/fm/stations", level="view")
        self.assertEqual((a["status"], a["stations"][0]["pi"], a["scannedAt"]), ("ok", "C201", events[0]["scannedAt"]))
        s, a = self.req("GET", "/api/dab/stations", level="view")
        self.assertEqual(a["ensembles"][0]["services"][0]["sid"], "C221")
        s, a = self.req("GET", "/api/state", level="view")
        self.assertEqual((a["bandScan"], a["stationsAt"]["fm"]), ({}, events[0]["scannedAt"]))

    def test_refusals(self):
        s, a = self.req("POST", "/api/scan", {"band": "lw"})
        self.assertEqual((s, a["code"]), (400, "bad_params"))
        # Automatic transmit armed: only the server knows.
        self.assertEqual(self.req("POST", "/api/set", {"mode": "ft8", "vfo": 14_074_000.0})[0], 200)
        s, a = self.req("POST", "/api/autotx", {"on": True, "remote": "tab1"}, level="transmit")
        self.assertEqual(s, 200, a)
        s, a = self.req("POST", "/api/scan", {"band": "fm"})
        self.assertEqual((s, a["code"], a["error"]), (409, "receiver_busy",
                                                     "Not scanning now: Automatic transmit is armed"))
        self.req("POST", "/api/autotx", {"on": False})
        self.req("POST", "/api/stop")
        s, a = self.req("POST", "/api/scan", {"band": "fm"})
        self.assertEqual((s, a["code"]), (503, "not_running"))

    def test_a_listener_arriving_takes_the_receiver_back(self):
        prior = {k: self.radio.state()[k] for k in ("vfo", "mode", "rptOffsetHz")}
        self.radio.bandscan.fm_lo, self.radio.bandscan.fm_hi = 87_500_000, 108_000_000
        self.assertEqual(self.req("POST", "/api/scan", {"band": "fm"})[0], 202)
        pump(self.radio, 30, until=lambda: (self.radio.state()["bandScan"] or {}).get("percent", 0) > 0)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request("GET", "/api/audio/rx", headers={shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "b",
                                                   "X-OpenHamShack-Level": "view"})
        r = c.getresponse()
        r.read(4800)
        c.close()
        self.assertTrue(scanned(self.radio, 30))
        s, a = self.req("GET", "/api/fm/stations", level="view")
        self.assertEqual((a["status"], a["statusText"]), ("aborted", "Stopped: the radio was wanted (listener)"))
        s, a = self.req("GET", "/api/status", level="view")
        self.assertEqual(({k: a[k] for k in ("vfo", "mode")}, a["rxOwner"]), ({"vfo": prior["vfo"],
                                                                                "mode": prior["mode"]}, {}))


class NbHasNone(test_server.ServerTest):
    def test_no_station_lists_in_qo100_nb(self):
        for method, path in (("GET", "/api/fm/stations"), ("GET", "/api/dab/stations"), ("POST", "/api/scan")):
            s, a = self.req(method, path, {"band": "fm"} if method == "POST" else None, level="control")
            self.assertEqual((s, a["code"]), (404, "not_found"), path)


if __name__ == "__main__":
    unittest.main()


class RdsText(unittest.TestCase):
    """PS and RadioText are published as a person reads them: stations pad
    PS to eight characters and RT with spaces and a carriage return."""

    def test_padding_and_carriage_return_are_trimmed(self):
        from ohsradio.bandscan import rds_text
        self.assertEqual(rds_text("BBC R3  "), "BBC R3")
        self.assertEqual(rds_text("Now Playing: Babydoll  \r"), "Now Playing: Babydoll")
        self.assertIsNone(rds_text("        "))
        self.assertIsNone(rds_text(None))
