"""Background decoder sessions pin Radio's capture (Brian, 23/10/2026;
RADIO-SDR-PLAN §8.5 "fixed sessions against a moving span").

- **Choosing the centre** (ohscore/span.py, numbers alone): the centre now
  when everything fits; else the middle of the sessions and the dial; never
  a session or the dial on DC; none when they cannot all fit; inside the
  device's reach.
- **On the band simulator** (Radio, faster than real time): a session pins
  the span and `span` says so; one off to the side moves the centre once;
  one too far is refused with a sentence; tuning inside the span moves the
  dial and never the centre, and the session decodes on without a reset;
  tuning out is refused with the sessions it would stop (from set(), a
  band button and a memory alike); saying yes stops them and the capture
  follows the dial again, while a change refused for another reason stops
  nothing; the last session stopping unpins; a dial put on DC moves the pin
  the least that clears it; saved sessions come back pinned.
- **Precedence** with what holds the whole receiver: DAB is refused while
  sessions pin the span unless told to stop them; no background session
  while DAB plays; no band scan while pinned, and a session ends a scan.
- **Transmit** follows the transmit dial, never the capture: a repeater's
  input outside the pinned span keys and goes out there.
- **Over the API:** 409 `span_pinned` with the sessions and the span,
  `dropSessions`, `span` in api/status, DAB's 409.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import tempfile
import unittest

from ham_helpers import close, make_radio, pump, speech
from listen_helpers import ListeningSim, make_listener
from test_server import SECRET

from ohscore import sdr
from ohscore.decoders import Refused
from ohscore.engine import SpanPinned
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohscore.span import DC_GUARD_HZ, choose_centre, fits
from ohsradio import server as ham_server
from ohsradio.radio import USABLE, Radio

# Seed 2's 20 m RTTY station (ohsradio/devices/sim.py, as test_decoders):
# its tones centred 1500 Hz above the 14.09175 MHz dial, on the air from
# the start. Radio's simulator runs at 1.2 MS/s: a span of 552 kHz.
SEED = 2
RTTY_HZ = 14_091_750.0 + 1500.0
TEXT = "CQ TEST"
DIAL = 14_070_000.0
HALF = USABLE * 1_200_000.0 / 2
HALF_24 = USABLE * 2_400_000.0 / 2      # an RSPdx's 2.4 MS/s: 1104 kHz


def text_after(view, rev):
    return "".join(r.get("text", "") for r in view["results"] if r["rev"] > rev and r.get("type") == "text")


class ChoosingTheCentre(unittest.TestCase):
    def test_the_centre_now_is_kept_when_everything_fits(self):
        self.assertEqual(choose_centre([(14_093_250, 1500), (14_070_000, 3000)], HALF, keep=14_175_000),
                         14_175_000)

    def test_otherwise_the_middle_of_the_sessions_and_the_dial(self):
        items = [(144_800_000, 6000), (145_500_000, 3000)]
        c = choose_centre(items, HALF_24, keep=145_600_000)      # 144.8 is 806 kHz from it: moved
        self.assertEqual(c, 145_148_000.0)          # (144.794 + 145.503) / 2, on a whole kHz
        self.assertTrue(fits(c, items, HALF_24))

    def test_never_a_session_or_the_dial_on_dc(self):
        # The middle of the outer two is exactly where the third sits.
        items = [(14_000_000, 1500), (14_200_000, 1500), (14_400_000, 1500)]
        c = choose_centre(items, HALF)
        self.assertTrue(fits(c, items, HALF))
        self.assertGreaterEqual(abs(c - 14_200_000), 1500 + DC_GUARD_HZ)
        self.assertLessEqual(abs(c - 14_200_000), 1500 + DC_GUARD_HZ + 1000)   # the least move that clears it
        # Nor is the centre kept when a new item would sit on it.
        self.assertNotEqual(choose_centre([(14_175_000, 1500)], HALF, keep=14_175_000), 14_175_000)

    def test_none_when_they_cannot_all_fit(self):
        self.assertIsNone(choose_centre([(14_000_000, 1500), (14_600_000, 3000)], HALF))
        # Two sessions that fill the span leave no centre off DC either.
        self.assertIsNone(choose_centre([(0, 1500), (2 * HALF - 3000, 1500)], HALF, guard=HALF))

    def test_the_device_range_bounds_it(self):
        c = choose_centre([(70_000_000, 1500)], HALF, lo=70_100_000)
        self.assertEqual(c, 70_100_000)
        self.assertIsNone(choose_centre([(70_000_000, 1500)], HALF, lo=70_600_000))


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class PinnedOnTheSimulator(unittest.TestCase):
    def setUp(self):
        self.r = make_radio(simSeed=SEED, simHourUtc=14.0, vfo=DIAL, mode="usb")
        self.r.start()
        self.addCleanup(close, self.r)

    def span(self):
        return self.r.state()["span"]

    def settled(self):
        # Until the move is published as well as made: the receive thread
        # (Radio._rx_done) clears pending_centre first, then sets the centre,
        # retunes the device and sets the notches, and only then puts the
        # new span in the status. Waiting for pending_centre alone, a loaded
        # host read the new centre against the old span between the two
        # (the beta.8 suite: 14.167 MHz against 14.175 MHz).
        pump(self.r, 5, until=lambda: self.r.pending_centre is None
             and self.span().get("centreHz") == self.r.centre)
        return self.r.centre

    def assert_clear(self, centre, *items):
        """Each (f, half width) inside the span around `centre` and off its DC."""
        for f, hw in items:
            self.assertLessEqual(abs(f - centre) + hw, HALF, (f, centre))
            self.assertGreaterEqual(abs(f - centre), hw + DC_GUARD_HZ, (f, centre))

    def test_a_session_pins_the_span_and_says_so(self):
        before = self.settled()
        self.assertEqual(self.span(), {"centreHz": before, "loHz": before - HALF, "hiHz": before + HALF,
                                       "pinned": False, "by": [], "sessions": []})
        sess = self.r.decoders.start("rtty", RTTY_HZ)
        sp = self.span()
        self.assertEqual((sp["centreHz"], sp["pinned"], sp["by"]), (before, True, [sess["id"]]))
        self.assertEqual(sp["sessions"], [{"id": sess["id"], "decoder": "rtty", "freqHz": RTTY_HZ,
                                           "label": "RTTY on 14.0933 MHz"}])
        self.assertEqual(self.settled(), before)          # it fitted: nothing retuned

    def test_a_session_off_to_one_side_moves_the_centre_once(self):
        before = self.settled()
        far = before - HALF - 20_000.0                     # outside the span now, near enough to the dial
        sess = self.r.decoders.start("rtty", far)
        c = self.settled()
        self.assertNotEqual(c, before)
        self.assertEqual(self.span()["centreHz"], c)
        self.assert_clear(c, (far, 1500.0), (DIAL, 3000.0))
        self.assertNotEqual(self.r.decoders.session(sess["id"])["state"], "outside")

    def test_a_session_too_far_from_the_dial_is_refused_with_a_sentence(self):
        with self.assertRaises(Refused) as cm:
            self.r.decoders.start("rtty", 7_050_000.0)
        self.assertEqual(cm.exception.code, "outside_span")
        self.assertEqual(str(cm.exception), "7.0500 MHz is too far from the dial (14.0700 MHz): the "
                                            "receiver covers 552 kHz at once, so tune nearer to it first")
        self.assertFalse(self.span()["pinned"])
        self.r.decoders.start("rtty", RTTY_HZ)
        with self.assertRaises(Refused) as cm:
            self.r.decoders.start("rtty", 14_650_000.0)
        self.assertIn("together with the dial (14.0700 MHz) and RTTY on 14.0933 MHz", str(cm.exception))

    def test_tuning_inside_the_span_moves_the_dial_not_the_centre_and_resets_nothing(self):
        sess = self.r.decoders.start("rtty", RTTY_HZ)
        centre = self.settled()
        pump(self.r, 60, until=lambda: TEXT in text_after(self.r.decoders.session(sess["id"]), 0))
        first = self.r.decoders.session(sess["id"])
        self.assertIn(TEXT, text_after(first, 0))
        states = []
        for vfo in (14_300_000.0, 13_950_000.0, 14_200_000.0, DIAL):
            self.r.set(vfo=vfo)
            self.assertEqual(self.r.state()["vfo"], vfo)
            self.assertEqual(self.r.centre, centre)
            self.assertIsNone(self.r.pending_centre)
            pump(self.r, 0.3)
            states.append(self.r.decoders.session(sess["id"])["state"])
        self.assertNotIn("outside", states)
        # The same session decodes on: its count of results carries on from
        # where it was (a reset would start a new session's), and the
        # station's next CQ is read after the retunes.
        mark = self.r.decoders.session(sess["id"])["rev"]
        pump(self.r, 60, until=lambda: TEXT in text_after(self.r.decoders.session(sess["id"]), mark))
        later = self.r.decoders.session(sess["id"])
        self.assertIn(TEXT, text_after(later, mark))
        self.assertEqual((later["id"], later["since"]), (first["id"], first["since"]))
        self.assertGreater(later["rev"], first["rev"])

    def test_tuning_out_is_refused_with_the_sessions_it_would_stop(self):
        sess = self.r.decoders.start("rtty", RTTY_HZ)
        centre = self.settled()
        with self.assertRaises(SpanPinned) as cm:
            self.r.set(vfo=7_050_000.0)
        e = cm.exception
        self.assertEqual(e.code, "span_pinned")
        self.assertEqual([s["id"] for s in e.sessions], [sess["id"]])
        self.assertEqual(str(e), "Tuning to 7.0500 MHz stops RTTY on 14.0933 MHz: the receiver stays on "
                                 "13.8990 MHz to 14.4510 MHz while they run")
        st = self.r.state()
        self.assertEqual((st["vfo"], st["band"], self.r.centre), (DIAL, "20m", centre))
        # The band buttons and the memories tune through set() too.
        with self.assertRaises(SpanPinned):
            self.r.band("40m")
        self.r.save_memory("away", 7_100_000.0, "lsb")
        with self.assertRaises(SpanPinned):
            self.r.recall("away")
        self.assertEqual(self.r.state()["vfo"], DIAL)
        # Wide FM's channel reaches 100 kHz: a mode can leave the span too.
        self.r.set(vfo=centre + HALF - 20_000.0)
        with self.assertRaises(SpanPinned):
            self.r.set(mode="wfm")

    def test_saying_yes_stops_them_and_the_capture_follows_again(self):
        self.r.decoders.start("rtty", RTTY_HZ)
        self.r.decoders.start("rtty", RTTY_HZ + 3000.0)
        self.r.set(vfo=7_050_000.0, drop_sessions=True)
        self.assertEqual(self.r.decoders.sessions(), [])
        self.assertEqual(self.r.state()["decoderSessions"], [])       # ended, so not started again
        c = self.settled()
        self.assertLess(abs(7_050_000.0 - c), HALF)
        self.assertEqual(self.span(), {"centreHz": c, "loHz": c - HALF, "hiHz": c + HALF, "pinned": False,
                                       "by": [], "sessions": []})

    def test_a_change_refused_for_another_reason_stops_nothing(self):
        sess = self.r.decoders.start("rtty", RTTY_HZ)
        with self.assertRaises(ValueError) as cm:
            self.r.set(vfo=7_050_000.0, mode="nonsense", drop_sessions=True)
        self.assertNotIsInstance(cm.exception, SpanPinned)
        self.assertEqual([s["id"] for s in self.r.decoders.sessions()], [sess["id"]])
        self.assertTrue(self.span()["pinned"])

    def test_the_last_session_stopping_unpins(self):
        a = self.r.decoders.start("rtty", RTTY_HZ)
        b = self.r.decoders.start("rtty", RTTY_HZ + 3000.0)
        self.r.decoders.stop(a["id"])
        self.assertEqual(self.span()["by"], [b["id"]])
        self.r.decoders.stop(b["id"])
        self.assertFalse(self.span()["pinned"])
        self.assertIsNone(self.r.pin)
        self.r.set(vfo=7_050_000.0)
        self.assertLess(abs(7_050_000.0 - self.settled()), HALF)

    def test_the_dial_onto_dc_moves_the_pin_the_least_that_clears_it(self):
        sess = self.r.decoders.start("rtty", RTTY_HZ)
        centre = self.settled()
        self.r.set(vfo=centre)
        moved = self.settled()
        self.assertNotEqual(moved, centre)
        self.assertLessEqual(abs(moved - centre), 3000.0 + DC_GUARD_HZ + 1000.0)
        self.assert_clear(moved, (centre, 3000.0), (RTTY_HZ, 1500.0))
        self.assertEqual((self.span()["centreHz"], self.span()["pinned"]), (moved, True))
        self.assertEqual(self.r.decoders.session(sess["id"])["id"], sess["id"])

    def test_saved_sessions_come_back_pinned_after_a_restart(self):
        self.r.decoders.start("rtty", RTTY_HZ)
        self.r.stop()
        self.assertEqual(self.r.state()["span"], {})
        self.r.start()
        sp = self.span()
        self.assertTrue(sp["pinned"])
        self.assertEqual([s["freqHz"] for s in sp["sessions"]], [RTTY_HZ])


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class Precedence(unittest.TestCase):
    """DAB and the band scan hold the whole receiver themselves."""
    HOME = 145_500_000.0

    def setUp(self):
        from test_ham_bandscan import on_air
        r, _audio, dev = make_listener([], receive_only=False, vfo=self.HOME, mode="fm")
        on_air(dev)
        self.addCleanup(close, r)
        self.r = r
        r.start()
        pump(r, 5, until=r._rx_settled)

    def test_dab_is_refused_while_sessions_pin_the_span_unless_told_to_stop_them(self):
        sess = self.r.decoders.start("rtty", self.HOME + 100_000.0)
        with self.assertRaises(Refused) as cm:
            self.r.decoders.start("dab", None, {"block": "11D", "service": ""})
        e = cm.exception
        self.assertEqual(e.code, "span_pinned")
        self.assertEqual(str(e), "Playing DAB takes the receiver to Band III and stops RTTY on 145.6000 MHz")
        self.assertEqual([s["id"] for s in e.sessions], [sess["id"]])
        self.assertEqual(self.r.state()["rxOwner"], {})
        dab = self.r.decoders.start("dab", None, {"block": "11D", "service": ""}, drop_sessions=True)
        self.assertEqual([s["id"] for s in self.r.decoders.sessions()], [dab["id"]])
        self.assertEqual(self.r.state()["rxOwner"]["session"], dab["id"])
        self.assertFalse(self.r.state()["span"]["pinned"])

    def test_no_background_session_while_dab_plays(self):
        self.r.decoders.start("dab", None, {"block": "11D", "service": ""})
        with self.assertRaises(Refused) as cm:
            self.r.decoders.start("rtty", 222_000_000.0)
        self.assertEqual(cm.exception.code, "receiver_busy")
        self.assertEqual(str(cm.exception), "The receiver is playing DAB from block 11D: stop the DAB station to "
                                            "add a decoder")

    def test_no_band_scan_while_pinned_and_a_session_ends_a_scan(self):
        from ohsradio.bandscan import Refused as ScanRefused
        from test_ham_bandscan import scanned
        sc = self.r.bandscan
        sess = self.r.decoders.start("rtty", self.HOME + 100_000.0)
        with self.assertRaises(ScanRefused) as cm:
            sc.scan_now("fm")
        self.assertEqual((cm.exception.code, str(cm.exception)), ("receiver_busy", "Not scanning now: A decoder is "
                                                                                    "running"))
        self.r.decoders.stop(sess["id"])
        centre = self.r.centre
        sc.fm_lo, sc.fm_hi = 87_500_000, 95_000_000
        sc.scan_now("fm")
        pump(self.r, 30, until=lambda: self.r.state()["rxOwner"].get("by") == "scan")
        self.assertEqual(self.r.state()["rxOwner"]["by"], "scan")
        sess = self.r.decoders.start("rtty", self.HOME + 100_000.0)
        # The scan gave the receiver back before the session was fitted:
        # it pins the operator's span, not the scan's hop.
        self.assertEqual(self.r.state()["rxOwner"], {})
        self.assertTrue(scanned(self.r, 30))
        self.assertEqual(self.r.bandscan.view("fm")["status"], "aborted")
        sp = self.r.state()["span"]
        self.assertEqual((sp["pinned"], sp["by"], sp["centreHz"]), (True, [sess["id"]], centre))


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class TransmitFollowsTheDial(unittest.TestCase):
    def test_a_key_up_goes_out_on_the_transmit_dial_outside_the_pinned_span(self):
        r = make_radio(audio_source=speech, simHourUtc=3.0, drive=0.5)
        r.set(authorise=True, licenceClass="full")
        r.start()
        self.addCleanup(close, r)
        # A repeater's output on the dial, its input 600 kHz below: outside
        # the span a session on 145.65 MHz pins.
        r.set(mode="fm", vfo=145_600_000.0, rptShift="minus", rptOffsetHz=600_000.0)
        r.decoders.start("rtty", 145_650_000.0)
        pump(r, 5, until=lambda: r.pending_centre is None)
        sp, centre = r.state()["span"], r.centre
        tx = r.state()["txDial"]
        self.assertEqual(tx, 145_000_000.0)
        self.assertTrue(sp["pinned"])
        self.assertLess(tx, sp["loHz"])
        self.assertEqual(r.state()["txBlocked"], "")
        r.ptt(True)
        pump(r, 10, until=lambda: r.dev.tx_active)
        self.assertTrue(r.dev.tx_active)
        self.assertTrue(r.state()["keyed"])
        # Out on the transmit dial through its own LO and offset; the
        # capture has not moved.
        self.assertAlmostEqual(r.tx_lo + r.tx_src.freq, tx, delta=1.0)
        self.assertAlmostEqual(r.dev.tx_lo, r.tx_lo, delta=1.0)
        self.assertEqual(r.centre, centre)
        r.ptt(False)
        pump(r, 5, until=lambda: not (r.tx_thread and r.tx_thread.is_alive()))
        self.assertEqual((r.centre, r.state()["span"]["pinned"]), (centre, True))


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class OverTheApi(unittest.TestCase):
    HOME = 145_500_000.0

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": self.HOME, "mode": "fm"}
        audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio,
                           device=ListeningSim(dict(cfg), 2_400_000.0, []))
        self.srv = Server(self.radio, ham_server.info("9.9.9"), audio, secret=SECRET)
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

    def test_span_pinned_and_drop_sessions(self):
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "rtty", "freqHz": 144_800_000.0})
        self.assertEqual(s, 201, a)
        sid = a["id"]
        s, st = self.req("GET", "/api/status", level="view")
        span = st["span"]
        self.assertEqual((span["pinned"], span["by"]), (True, [sid]))
        self.assertLessEqual(span["loHz"], 144_800_000.0 - 1500)
        self.assertGreaterEqual(span["hiHz"], self.HOME + 3000)
        # Inside: the dial moves. Outside: 409 with what it would stop.
        s, a = self.req("POST", "/api/set", {"changes": {"vfo": 145_000_000.0}})
        self.assertEqual((s, a["changed"]), (200, {"vfo": 145_000_000.0}))
        s, a = self.req("POST", "/api/set", {"changes": {"vfo": 432_200_000.0}})
        self.assertEqual((s, a["code"]), (409, "span_pinned"))
        self.assertTrue(a["error"].startswith("Tuning to 432.2000 MHz stops RTTY on 144.8000 MHz"))
        self.assertEqual(a["sessions"], [{"id": sid, "decoder": "rtty", "freqHz": 144_800_000.0,
                                          "label": "RTTY on 144.8000 MHz"}])
        self.assertEqual(a["span"], span)
        # Any route that tunes says the same (a memory).
        self.radio.save_memory("70cm", 432_200_000.0, "usb")
        s, a = self.req("POST", "/api/recall", {"name": "70cm"})
        self.assertEqual((s, a["code"]), (409, "span_pinned"))
        # DAB says so too, with the sessions.
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "dab", "params": {"block": "11D"}})
        self.assertEqual((s, a["code"], [x["id"] for x in a["sessions"]]), (409, "span_pinned", [sid]))
        # Yes: in the flat form too, and never taken for a setting.
        s, a = self.req("POST", "/api/set", {"vfo": 432_200_000.0, "dropSessions": True})
        self.assertEqual((s, a["changed"]["vfo"]), (200, 432_200_000.0), a)
        s, st = self.req("GET", "/api/status", level="view")
        self.assertEqual((st["span"]["pinned"], st["decoders"]["sessions"]), (False, 0))
        s, a = self.req("GET", "/api/decoders", level="view")
        self.assertEqual(a["sessions"], [])


if __name__ == "__main__":
    unittest.main()
