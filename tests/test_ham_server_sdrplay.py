"""Radio's store form with an SDRplay RSP lent by the broker (12/10/2026,
an RSPdx on ohs-box): the soapy device is the broker's sdrplay-1, the
claim's USB access decides the SoapySDR arguments as an address decides a
Pluto's, and a receiver is never keyed - the key-up is refused before the
broker hears of it. The engine is Radio's band simulator posing as the
receive-only SDR; the broker is test_server's fake with a USB answer."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest

from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.devices.sim import HamSim
from ohsradio.radio import Radio
from test_server import SECRET, FakeBroker


class ReceiverSim(HamSim):
    """The simulator as a receive-only SDR, as SoapyDevice is."""
    can_tx = False


class UsbBroker(FakeBroker):
    """Lends a USB device: access says reach usb, as the edition's broker
    does for a class with no address (dock360 shack/broker.py)."""

    serial = ""

    def __call__(self, method, path, body=None, headers=None):
        status, answer = super().__call__(method, path, body, headers)
        if method == "POST" and path == "/broker/claims" and status == 201:
            answer["access"] = {"reach": "usb", "usbId": "1df7:3030", "serial": self.serial}
        return status, answer


class SdrplayThroughTheBroker(unittest.TestCase):
    serial = ""
    args = "driver=rtlsdr"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "soapy", "soapyArgs": self.args, "soapyAntenna": "Antenna C",
               "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 20.0,
               "callsign": "GM4BRI", "licenceClass": "full", "vfo": 3_650_000.0, "mode": "lsb"}
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio,
                           device=ReceiverSim(dict(cfg), 1_200_000.0))
        self.fake = UsbBroker()
        self.fake.serial = self.serial
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET,
                          broker=shack.BrokerClient(self.fake))
        self.srv.serve("127.0.0.1", 0)
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def test_the_soapy_receiver_is_the_brokers_sdrplay(self):
        self.assertEqual(self.srv.device(), "sdrplay-1")
        claims = self.fake.claim_bodies()
        self.assertEqual([(b["device"], b["mode"]) for b in claims], [("sdrplay-1", "rx")])

    def test_the_claim_decides_the_soapysdr_arguments(self):
        self.assertEqual(self.radio.st["soapyArgs"], "driver=sdrplay")
        # The antenna is the station's choice, not the broker's.
        self.assertEqual(self.radio.st["soapyAntenna"], "Antenna C")

    def test_a_receiver_is_never_keyed_and_the_broker_never_asked(self):
        self.assertFalse(self.radio.state()["canTx"])
        why = self.srv.key("tv-1", "brian")
        self.assertEqual(why, "This radio can only receive")
        self.assertFalse(self.radio.state()["keyed"])
        self.assertIsNone(self.srv.lease)
        self.assertEqual([b["mode"] for b in self.fake.claim_bodies()], ["rx"])
        self.assertFalse([p for m, p, _b, _h in self.fake.calls if p.endswith("/onair")])

    def test_automatic_transmit_is_refused_the_same_way(self):
        why = self.srv.key("tv-1", "brian", start=lambda: self.fail("an over was started"), digital=True)
        self.assertEqual(why, "This radio can only receive")


class SdrplayWithASerial(SdrplayThroughTheBroker):
    serial = "2105012345"

    def test_the_claim_decides_the_soapysdr_arguments(self):
        self.assertEqual(self.radio.st["soapyArgs"], "driver=sdrplay,serial=2105012345")


class SdrplayKeepsTheDriversOwnSettings(SdrplayThroughTheBroker):
    """The station's driver settings survive the claim (an RSPdx's LNA
    state); the driver and serial are the claim's, and nothing that is not
    a plain key=value is passed on."""
    args = "driver=rtlsdr,serial=999,rfgain_sel=4, rfnotch_ctrl=true,bad key=1,x=a;b"

    def test_the_claim_decides_the_soapysdr_arguments(self):
        self.assertEqual(self.radio.st["soapyArgs"], "driver=sdrplay,rfgain_sel=4,rfnotch_ctrl=true")


class NotForTheOtherRadios(unittest.TestCase):
    def test_the_pluto_and_hl2_keep_their_names(self):
        info = ham_server.info("9.9.9")
        self.assertEqual(info.device_for("pluto"), "pluto-1")
        self.assertEqual(info.device_for("hl2"), "hl2-1")
        self.assertEqual(info.device_for("sim"), "")


if __name__ == "__main__":
    unittest.main()
