"""S-meter calibration over Radio's store API (docs/SERVER-API.md "S-meter
calibration"): GET/POST/DELETE api/smeter/calibrate, the meter feed's new
dbm/s/why/whyText fields, and that QO-100 NB (which has none of this -
ohscore/smeter_cal.py docstring) answers 404 not_found, the same pattern
api/overpower already uses for an NB-only feature in reverse.

The engine is Radio's band simulator posing as an SDRplay RSP (as
test_ham_server_sdrplay.py's ReceiverSim does), so rxGainMode and
sdrplayLna behave exactly as they would on real hardware, without an
RSP or its API installed."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest

from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.devices.sim import HamSim
from ohsradio.radio import Radio
from test_server import SECRET, ServerTest


class ReceiverSim(HamSim):
    """The simulator as a receive-only SDR, as the SDRplay RSP is."""
    can_tx = False


RSPDX_CFG = {"device": "sdrplay", "sdrSerial": "191101D142", "soapyAntenna": "Antenna A",
             "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
             "callsign": "GM4BRI", "licenceClass": "full", "vfo": 145_650_000.0, "mode": "fm",
             "rxGainMode": "manual", "rxGain": 40.0, "sdrplayLna": 4}


class SMeterOverTheApi(ServerTest):
    def setUp(self):  # noqa: D102 - ServerTest.setUp rebuilt with the RSP fake injected, no broker
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(dict(RSPDX_CFG), persist=False, data_dir=tmp.name, audio=self.audio,
                           device=ReceiverSim(dict(RSPDX_CFG), 1_200_000.0))
        self.now = [0.0]
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET, broker=None,
                          clock=lambda: self.now[0])
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")
        self.assertEqual(self.radio.st.get("band"), "2m", self.radio.st)

    def test_get_with_nothing_stored_is_an_empty_table(self):
        s, a = self.req("GET", "/api/smeter/calibrate", level="view")
        self.assertEqual((s, a), (200, {"calibrations": {}}))

    def test_post_dbfs_and_dbm_stores_a_calibration_get_then_lists_it(self):
        s, a = self.req("POST", "/api/smeter/calibrate", {"dbfs": -42.6, "dbm": -93.0}, level="control")
        self.assertEqual(s, 200, a)
        self.assertAlmostEqual(a["calibration"]["offset"], -50.4, places=2)
        self.assertAlmostEqual(a["calibration"]["gain"], 40.0)
        s, a = self.req("GET", "/api/smeter/calibrate", level="view")
        self.assertEqual(s, 200)
        self.assertEqual(len(a["calibrations"]), 1)
        rec = next(iter(a["calibrations"].values()))
        self.assertAlmostEqual(rec["offset"], -50.4, places=2)

    def test_post_dbm_alone_uses_the_current_reading(self):
        self.radio.rx_level = -42.6
        self.radio._smeter_hist.append(-42.6)
        s, a = self.req("POST", "/api/smeter/calibrate", {"dbm": -93.0}, level="control")
        self.assertEqual(s, 200, a)
        self.assertAlmostEqual(a["calibration"]["offset"], -50.4, places=2)

    def test_dbm_out_of_range_or_non_numeric_is_refused(self):
        for bad in (-1000.0, 1000.0, "banana", None):
            s, a = self.req("POST", "/api/smeter/calibrate", {"dbm": bad}, level="control")
            self.assertEqual(s, 400, (bad, a))
            self.assertEqual(a["code"], "bad_params")

    def test_dbm_missing_is_refused(self):
        s, a = self.req("POST", "/api/smeter/calibrate", {"dbfs": -42.6}, level="control")
        self.assertEqual(s, 400, a)
        self.assertEqual(a["code"], "bad_params")

    def test_agc_on_refuses_with_a_sentence(self):
        s, a = self.req("POST", "/api/set", {"rxGainMode": "slow_attack"}, level="control")
        self.assertEqual(s, 200, a)
        s, a = self.req("POST", "/api/smeter/calibrate", {"dbfs": -42.6, "dbm": -93.0}, level="control")
        self.assertEqual(s, 409, a)
        self.assertEqual(a["code"], "cannot_calibrate")
        self.assertTrue(a["error"])

    def test_view_level_cannot_calibrate_or_clear(self):
        s, a = self.req("POST", "/api/smeter/calibrate", {"dbm": -93.0}, level="view")
        self.assertEqual((s, a["code"]), (403, "level_too_low"))
        s, a = self.req("DELETE", "/api/smeter/calibrate", level="view")
        self.assertEqual((s, a["code"]), (403, "level_too_low"))

    def test_delete_clears_it(self):
        s, a = self.req("POST", "/api/smeter/calibrate", {"dbfs": -42.6, "dbm": -93.0}, level="control")
        self.assertEqual(s, 200, a)
        s, a = self.req("DELETE", "/api/smeter/calibrate", level="control")
        self.assertEqual((s, a), (200, {"ok": True}))
        s, a = self.req("GET", "/api/smeter/calibrate", level="view")
        self.assertEqual(a["calibrations"], {})

    def test_delete_with_nothing_stored_still_answers_ok(self):
        s, a = self.req("DELETE", "/api/smeter/calibrate", level="control")
        self.assertEqual((s, a), (200, {"ok": True}))

    def test_the_meter_feed_carries_dbm_and_s_once_calibrated(self):
        s, a = self.req("POST", "/api/smeter/calibrate", {"dbfs": -42.6, "dbm": -93.0}, level="control")
        self.assertEqual(s, 200, a)
        self.radio.rx_level = -42.6
        extra = self.radio._meter_extra(self.radio.st)
        self.assertAlmostEqual(extra["dbm"], -93.0, places=1)
        self.assertEqual(extra["s"], "S9")
        self.assertIsNone(extra["why"])
        self.assertEqual(extra["whyText"], "")
        # The raw dBFS field this rides beside is untouched by any of this.
        self.assertIn("fwd", extra)

    def test_the_meter_feed_says_why_before_any_calibration(self):
        extra = self.radio._meter_extra(self.radio.st)
        self.assertIsNone(extra["dbm"])
        self.assertIsNone(extra["s"])
        self.assertEqual(extra["why"], "no_calibration")
        self.assertTrue(extra["whyText"])


class NbHasNone(unittest.TestCase):
    def test_qo100_nb_answers_404_not_found(self):
        import helpers
        from ohscore.server.app import Server
        from ohsnb import server as nb_server
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        from ohsnb.radio import Radio as NbRadio
        audio = StreamAudio(realtime=False)
        radio = NbRadio(helpers.sim_cfg(callsign="GM4BRI", licenceClass="full"), persist=False,
                        data_dir=tmp.name, audio=audio)
        srv = Server(radio, nb_server.info("9.9.9"), audio, secret=SECRET, broker=None)
        httpd = srv.serve("127.0.0.1", 0)
        self.addCleanup(srv.shutdown)
        self.assertEqual(srv.start_radio(), "")
        import http.client
        import json
        from ohscore.server import shack
        c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=20)
        h = {shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "brian",
             "X-OpenHamShack-Level": "view", "X-OpenHamShack-Device": "dev_TEST",
             "X-OpenHamShack-Auth": "device"}
        c.request("GET", "/api/smeter/calibrate", None, h)
        r = c.getresponse()
        status, body = r.status, json.loads(r.read())
        c.close()
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
