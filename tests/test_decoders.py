"""Decoder sessions in the engine (ohscore/decoders.py, RADIO-SDR-PLAN §4.3),
run for real on Radio's band simulator faster than real time: a fixed RTTY
session copies the simulated 20 m RTTY station from the engine's own filter
bank while the dial is elsewhere; the mode decoder is the session "vfo";
results come out numbered on the `decoders` feed and are kept for a client
that missed some; a session the span no longer covers goes `outside` and
comes back by itself; the limits and refusals are codes with sentences;
sessions are saved and start again with the radio; and stopping the radio
closes the host."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ham_helpers import close, make_radio, pump

from ohscore import sdr
from ohscore.decoders import Refused

# Seed 2's 20 m RTTY station (ohsradio/devices/sim.py): dial 14.09175 MHz
# USB, its tones centred 1500 Hz above, on the air from the start.
SEED = 2
RTTY_HZ = 14_091_750.0 + 1500.0
TEXT = "CQ TEST"


def text_of(items, session):
    return "".join(i.get("text", "") for i in items if i.get("session") == session and i.get("type") == "text")


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class FixedSessions(unittest.TestCase):
    def setUp(self):
        self.r = make_radio(simSeed=SEED, simHourUtc=14.0, vfo=14_070_000.0, mode="usb")
        self.feed = self.r.subscribe("decoders", 5000)
        self.r.start()
        self.addCleanup(close, self.r)

    def test_a_session_copies_the_station_away_from_the_dial(self):
        sess = self.r.decoders.start("rtty", RTTY_HZ)
        self.assertEqual((sess["decoder"], sess["freqHz"], sess["panel"]), ("rtty", RTTY_HZ, "text"))
        got = pump(self.r, 60, feeds=[self.feed], until=lambda: TEXT in text_of(self.r.decoders.session(
            sess["id"])["results"], sess["id"]))["decoders"]
        self.assertIn(TEXT, text_of(got, sess["id"]))
        revs = [i["rev"] for i in got if i["session"] == sess["id"]]
        self.assertEqual(revs, list(range(revs[0], revs[0] + len(revs))))
        # A client that missed some asks again from the last rev it had.
        later = self.r.decoders.session(sess["id"], since=revs[len(revs) // 2])["results"]
        self.assertEqual([i["rev"] for i in later][0], revs[len(revs) // 2] + 1)
        view = self.r.decoders.session(sess["id"])
        self.assertIn(view["state"], ("synced", "nosignal", "running"))
        self.assertEqual(self.r.state()["decoders"]["sessions"], 1)

    def test_a_session_the_span_leaves_goes_outside_and_comes_back(self):
        sess = self.r.decoders.start("rtty", RTTY_HZ)
        self.r.set(vfo=7_050_000.0)
        pump(self.r, 30, until=lambda: self.r.decoders.session(sess["id"])["state"] == "outside")
        view = self.r.decoders.session(sess["id"])
        self.assertEqual((view["state"], view["why"]), ("outside", "outside_span"))
        self.assertTrue(view["whyText"])
        self.r.set(vfo=14_070_000.0)
        pump(self.r, 30, until=lambda: self.r.decoders.session(sess["id"])["state"] != "outside")
        self.assertNotEqual(self.r.decoders.session(sess["id"])["state"], "outside")

    def test_refusals_are_codes_with_sentences(self):
        for args, code in ((("nope", RTTY_HZ), "unknown_decoder"), (("rtty", 7_050_000.0), "outside_span"),
                           (("rtty", RTTY_HZ, {"baud": 46.0}), "bad_params")):
            with self.subTest(code=code):
                with self.assertRaises(Refused) as cm:
                    self.r.decoders.start(*args)
                self.assertEqual(cm.exception.code, code)
                self.assertTrue(str(cm.exception))

    def test_no_more_sessions_than_the_setting_allows(self):
        self.r.stop()
        self.r.set(decodersMax=1)
        self.r.start()
        self.r.decoders.start("rtty", RTTY_HZ)
        with self.assertRaises(Refused) as cm:
            self.r.decoders.start("rtty", RTTY_HZ + 2000.0)
        self.assertEqual(cm.exception.code, "too_many_sessions")

    def test_sessions_are_saved_and_start_again_with_the_radio(self):
        a = self.r.decoders.start("rtty", RTTY_HZ, {"baud": 50.0})
        b = self.r.decoders.start("rtty", RTTY_HZ + 3000.0)
        self.assertEqual(self.r.state()["decoderSessions"],
                         [{"decoder": "rtty", "freqHz": RTTY_HZ, "params": {"baud": 50.0}},
                          {"decoder": "rtty", "freqHz": RTTY_HZ + 3000.0, "params": {}}])
        self.assertTrue(self.r.decoders.stop(b["id"]))
        self.r.stop()
        self.assertEqual(self.r.decoders.sessions(), [])
        self.r.start()
        again = self.r.decoders.sessions()
        self.assertEqual([(s["decoder"], s["freqHz"], s["params"]) for s in again],
                         [("rtty", RTTY_HZ, {"baud": 50.0})])
        self.assertNotEqual(again[0]["id"], a["id"])

    def test_stopping_the_radio_closes_the_host(self):
        self.r.decoders.start("rtty", RTTY_HZ)
        self.r.stop()
        self.assertIsNone(self.r.decoders.host)
        with self.assertRaises(Refused) as cm:
            self.r.decoders.start("rtty", RTTY_HZ)
        self.assertEqual(cm.exception.code, "not_running")


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class ModeDecoder(unittest.TestCase):
    def test_the_rtty_mode_is_the_session_vfo_and_still_sends_events(self):
        r = make_radio(simSeed=SEED, simHourUtc=14.0, vfo=RTTY_HZ - 1000.0, mode="rtty")
        events, feed = r.subscribe("events", 5000), r.subscribe("decoders", 5000)
        r.start()
        try:
            got = pump(r, 60, feeds=[events, feed], until=lambda: TEXT in "".join(
                i.get("text", "") for i in (r.decoders.session("vfo") or {}).get("results", [])))
            heard = "".join(e.get("text", "") for e in got["events"] if e.get("mode") == "rtty")
            self.assertIn(TEXT, heard)
            self.assertIn(TEXT, text_of(got["decoders"], "vfo"))
            ids = [s["id"] for s in r.decoders.sessions()]
            self.assertEqual(ids, ["vfo"])
            r.set(mode="usb")
            pump(r, 10, until=lambda: not r.decoders.sessions())
            self.assertEqual(r.decoders.sessions(), [])
        finally:
            close(r)


class WithoutTheLibrary(unittest.TestCase):
    def test_the_catalogue_is_empty_and_rtty_says_why(self):
        from unittest import mock
        from ohscore import modes_glue
        with mock.patch.object(sdr, "load", return_value=None):
            self.assertTrue(sdr.why())
            r = make_radio()
            try:
                self.assertEqual(r.decoders.catalogue(), [])
                with self.assertRaises(Refused) as cm:
                    r.decoders.start("rtty", 14_000_000.0)
                self.assertEqual(cm.exception.code, "decoder_unavailable")
            finally:
                close(r)
        self.assertIn("rtty", modes_glue.available(["rtty"]))


if __name__ == "__main__":
    unittest.main()
