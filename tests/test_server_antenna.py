"""The antenna setting over the store API (docs/SERVER-API.md): read at
view level under `deviceStatus` and `soapyAntennaLabels`, changed at
control level through `api/set` - neither key is a device address
(PLATFORM_KEYS) or a station-profile key (PROFILE_KEYS), so both are the
operator's to set here, unlike soapyArgs/plutoUri."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest

from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.radio import Radio
from test_ham_antenna import FakeAntennaDevice
from test_server import SECRET, ServerTest


class AntennaOverTheApi(ServerTest):
    def setUp(self):  # noqa: D102 - ServerTest.setUp rebuilt with FakeAntennaDevice injected, no broker
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dev = FakeAntennaDevice(initial="Antenna A")
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "callsign": "GM4BRI",
               "licenceClass": "foundation", "soapyAntenna": "Antenna A"}
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio, device=self.dev)
        self.now = [0.0]
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET, broker=None,
                          clock=lambda: self.now[0])
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def test_the_input_list_and_current_antenna_are_in_state(self):
        self.assertTrue(self.wait(lambda: self.req("GET", "/api/state", level="view")[1]
                                   .get("deviceStatus", {}).get("antenna")))
        s, a = self.req("GET", "/api/state", level="view")
        self.assertEqual(s, 200)
        self.assertEqual(a["deviceStatus"]["antenna"], "Antenna A")
        self.assertEqual(a["deviceStatus"]["antennas"], ["Antenna A", "Antenna B", "Antenna C"])

    def test_control_level_can_change_the_antenna(self):
        s, a = self.req("POST", "/api/set", {"soapyAntenna": "Antenna C"}, level="control")
        self.assertEqual((s, a), (200, {"changed": {"soapyAntenna": "Antenna C"}}))
        self.assertTrue(self.wait(lambda: self.dev.antenna == "Antenna C"))

    def test_view_level_cannot_change_it(self):
        s, a = self.req("POST", "/api/set", {"soapyAntenna": "Antenna C"}, level="view")
        self.assertEqual((s, a["code"]), (403, "level_too_low"))

    def test_control_level_can_set_a_label_as_one_line_of_json(self):
        s, a = self.req("POST", "/api/set", {"soapyAntennaLabels": '{"Antenna C":"80 m dipole"}'},
                        level="control")
        self.assertEqual(s, 200, a)
        s, a = self.req("GET", "/api/state", level="view")
        self.assertEqual(a["soapyAntennaLabels"], '{"Antenna C":"80 m dipole"}')

    def test_an_unknown_antenna_is_refused_by_the_running_device_not_the_route(self):
        # api/set itself does not know the driver's own list (only the
        # open device does, through listAntennas); the refusal shows up
        # as a toast and the antenna not moving, same as Settings sees it.
        s, a = self.req("POST", "/api/set", {"soapyAntenna": "Antenna Z"}, level="control")
        self.assertEqual(s, 200, a)
        self.assertTrue(self.wait(lambda: "Antenna Z" in self.dev.calls))
        self.assertEqual(self.dev.antenna, "Antenna A")


if __name__ == "__main__":
    unittest.main()
