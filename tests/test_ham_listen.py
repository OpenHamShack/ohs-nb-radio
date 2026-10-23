"""The listening areas Remote puts in Radio's band list (openhamshack-remote
docs/RADIO-LISTEN-CONTRACT.md §2), on a receiver shaped like the RSPdx:
a dial anywhere in each area is taken, the whole passband sits inside the
receiver's span there, a station there is heard in the area's mode, and
transmit there is refused - by the receiver itself, and on a radio that
could transmit, by the licence with the sentence it always gives.

Also the 8.33 kHz airband raster: a dial in whole Hz is kept to the hertz
in state, through api/set, in the channel the engine cuts and in what is
heard."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import re
import tempfile
import unittest

from ohscore.engine import TxRefused
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.radio import Radio

from ham_helpers import close, pump
from listen_helpers import HEARD, ListeningSim, Station, make_listener, peak_hz, tone_snr
from test_server import SECRET, ServerTest

# (name, lowest dial, highest dial, mode, step) - the contract's table. DAB
# is a decoder session (§3), not a mode: only its dial is asked of here.
AREAS = [
    ("LW broadcast", 148_500, 283_500, "am", 9_000),
    ("MW broadcast", 526_500, 1_606_500, "am", 9_000),
    ("CB (CEPT)", 26_965_000, 27_405_000, "fm", 10_000),
    ("CB (UK 27/81)", 27_601_250, 27_991_250, "fm", 10_000),
    ("Broadcast FM", 87_500_000, 108_000_000, "wfm", 100_000),
    ("Airband", 118_000_000, 137_000_000, "am", 25_000 / 3),
    ("Marine VHF", 156_000_000, 162_025_000, "fm", 25_000),
    ("DAB (Band III)", 174_000_000, 240_000_000, None, 1_712_000),
    ("LPD433", 433_075_000, 434_775_000, "fm", 25_000),
    ("PMR446", 446_006_250, 446_193_750, "fm", 12_500),
]
RECEIVER_SAYS = "This radio can only receive"
NOT_AMATEUR = re.compile(r"^[\d.]+-[\d.]+ [kM]Hz is not an amateur band$")
WFM_SAYS = "WFM is for listening only: nothing is ever transmitted in it"


def channel(lo, hi, step):
    """A channel near the middle of an area, on its raster, in whole Hz."""
    return lo + round(round((hi - lo) / 2 / step) * step)


def dials(lo, hi, step):
    return [lo, channel(lo, hi, step), hi]


def settle(r):
    """Until the receive thread has moved the centre for the last set() and
    said so in state. _rx_settled() alone is the receive thread's own test:
    read from here it can pass in the instant between _rx_done clearing the
    pending centre and publishing the new span."""
    pump(r, 10, until=lambda: r._rx_settled() and r.pending_centre is None
         and r.state()["spanLo"] == r.wide_span()[0])
    pump(r, 0.2)


class EveryAreaIsHeard(unittest.TestCase):
    """One RSPdx-shaped receiver, walked through every area."""

    def setUp(self):
        stations = [Station(channel(lo, hi, step), mode) for _n, lo, hi, mode, step in AREAS if mode]
        self.r, self.audio, self.dev = make_listener(stations, vfo=145_500_000.0, mode="fm")
        self.addCleanup(close, self.r)
        self.r.start()
        settle(self.r)

    def test_a_dial_anywhere_in_each_area_is_taken_and_inside_the_span(self):
        for name, lo, hi, mode, step in AREAS:
            for dial in dials(lo, hi, step):
                with self.subTest(area=name, dial=dial):
                    self.r.set(vfo=float(dial), mode=mode or "am")
                    settle(self.r)
                    st = self.r.state()
                    self.assertEqual(st["vfo"], dial)
                    self.assertEqual(st["rxDial"], dial)
                    # The whole passband, not only the dial, is inside what
                    # the receiver hears now.
                    self.assertLessEqual(st["spanLo"], dial + st["rxFilterLo"])
                    self.assertGreaterEqual(st["spanHi"], dial + st["rxFilterHi"])

    def test_a_station_in_each_area_is_heard_in_its_mode(self):
        for name, lo, hi, mode, step in AREAS:
            if mode is None:
                continue
            with self.subTest(area=name, mode=mode):
                self.r.set(vfo=float(channel(lo, hi, step)), mode=mode)
                settle(self.r)
                pump(self.r, 0.5)
                self.audio.take()
                pump(self.r, 30, until=lambda: sum(len(c) for c in self.audio.chunks) >= 1.5 * HEARD)
                a = self.audio.take()[4800:]
                peak, snr = tone_snr(a, 1000.0)
                self.assertAlmostEqual(peak, 1000.0, delta=10)
                self.assertGreater(snr, 20.0)

    def test_the_receiver_refuses_to_transmit_in_every_area(self):
        for name, lo, hi, mode, step in AREAS:
            with self.subTest(area=name):
                self.r.set(vfo=float(channel(lo, hi, step)), mode=mode or "am")
                want = WFM_SAYS if mode == "wfm" else RECEIVER_SAYS
                self.assertEqual(self.r.state()["txBlocked"], want)
                with self.assertRaises(TxRefused):
                    self.r.ptt(True)
                self.assertFalse(self.r.state()["keyed"])


class TheLicenceRefusesThere(unittest.TestCase):
    """The same areas on the transmitting simulator over the same range, a
    Full licence: the licence's own sentence, nothing keyed. LPD433 is the
    exception, and rightly: 433.075-434.775 MHz is inside 70 cm, where FM
    is the amateur's (433.500 is the UK's FM calling channel). Wide FM is
    refused as itself whatever the licence says."""

    def setUp(self):
        self.r, _audio, _dev = make_listener([], receive_only=False, vfo=145_500_000.0, mode="fm")
        self.addCleanup(close, self.r)
        self.r.start()

    def test_outside_the_amateur_bands_the_licence_refuses(self):
        for name, lo, hi, mode, step in AREAS:
            for dial in dials(lo, hi, step):
                with self.subTest(area=name, dial=dial):
                    self.r.set(vfo=float(dial), mode="fm" if mode == "wfm" else (mode or "am"))
                    why = self.r.state()["txBlocked"]
                    if name == "LPD433":
                        self.assertEqual(self.r.state()["band"], "70cm")
                        self.assertNotRegex(why, NOT_AMATEUR)
                        continue
                    self.assertRegex(why, NOT_AMATEUR)
                    with self.assertRaises(TxRefused) as e:
                        self.r.ptt(True)
                    self.assertEqual(str(e.exception), why)
                    self.assertFalse(self.r.state()["keyed"])

    def test_broadcast_fm_in_wfm_is_refused_as_wfm(self):
        self.r.set(vfo=97_700_000.0, mode="wfm")
        self.assertEqual(self.r.state()["txBlocked"], WFM_SAYS)
        with self.assertRaises(TxRefused):
            self.r.ptt(True)
        self.assertFalse(self.r.state()["keyed"])


AIRBAND_DIAL = 118_008_333          # 118.008333 MHz: the 8.33 kHz raster's first channel above 118


class WholeHzDials(unittest.TestCase):
    """An 8.33 kHz channel is not on any 10 Hz or 1 kHz grid. Nothing on the
    way from set() to the ear may move it: the test station is a carrier
    exactly 1 kHz above the dial, heard in USB, so a dial rounded by even
    3 Hz (to 118 008 330) would be heard as a 1003 Hz tone."""

    def test_state_the_channel_and_the_ear_keep_the_hertz(self):
        r, audio, _dev = make_listener([Station(AIRBAND_DIAL + 1000.0, "am", tone=200.0, level_db=-40.0)],
                                       vfo=145_500_000.0, mode="fm")
        self.addCleanup(close, r)
        r.start()
        r.set(vfo=float(AIRBAND_DIAL), mode="am")
        settle(r)
        st = r.state()
        self.assertEqual((st["vfo"], st["rxDial"]), (AIRBAND_DIAL, AIRBAND_DIAL))
        r.set(mode="usb", filterLo=300.0, filterHi=2700.0)
        settle(r)
        pump(r, 0.5)
        self.assertEqual(r.vfo_ch.freq + r.centre, AIRBAND_DIAL)        # the channel the engine cuts
        audio.take()
        pump(r, 60, until=lambda: sum(len(c) for c in audio.chunks) >= HEARD * 8)
        a = audio.take()[4800:]
        # The carrier's line, to a fraction of the 0.13 Hz bins of 8 s.
        self.assertAlmostEqual(peak_hz(a), 1000.0, delta=0.5)
        self.assertEqual(r.state()["vfo"], AIRBAND_DIAL)


class WholeHzOverTheApi(ServerTest):
    """api/set and api/state carry the dial as it was sent."""

    def setUp(self):  # noqa: D102 - ServerTest.setUp with Radio on the RSPdx-shaped simulator, no broker
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSignals": False,
               "callsign": "GM4BRI", "licenceClass": "full", "vfo": 145_500_000.0, "mode": "fm"}
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio,
                           device=ListeningSim(dict(cfg)))
        self.now = [0.0]
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET, broker=None,
                          clock=lambda: self.now[0])
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def test_an_8_33_khz_channel_round_trips(self):
        s, a = self.req("POST", "/api/set", {"changes": {"vfo": AIRBAND_DIAL, "mode": "am"}}, level="control")
        self.assertEqual(s, 200, a)
        self.assertEqual(a["changed"]["vfo"], AIRBAND_DIAL)
        s, a = self.req("GET", "/api/state", level="view")
        self.assertEqual((a["vfo"], a["rxDial"]), (AIRBAND_DIAL, AIRBAND_DIAL))

    def test_wfm_and_its_width_over_the_api(self):
        s, a = self.req("POST", "/api/set", {"changes": {"vfo": 97_700_000, "mode": "wfm"}}, level="control")
        self.assertEqual(s, 200, a)
        s, a = self.req("GET", "/api/state", level="view")
        self.assertEqual((a["mode"], a["rxFilterLo"], a["rxFilterHi"]), ("wfm", -90_000.0, 90_000.0))
        self.assertIn("wfm", self.req("GET", "/api/spec", level="view")[1]["mode"]["choices"])
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "tv-1"}, level="transmit")
        self.assertEqual(s, 200, a)
        self.assertFalse(a["onAir"])


if __name__ == "__main__":
    unittest.main()
