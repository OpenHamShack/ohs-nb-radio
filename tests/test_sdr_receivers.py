"""Radio's RTL-SDR and SDRplay receivers through shack_sdr's own bindings
(ohscore/devices/sdrsource.py; RADIO-SDR-PLAN §6), run for real: the
engine receives from a stand-in librtlsdr built from C at test time (the
library's own tests do the same) - opens it at the rate asked, tunes it
where the dial wants, maps the gain control onto its tuner, and never
keys it; an RSP offers only 2.4 MS/s; without SDRplay's API the RSP says
to install it (on a controller, to ask the administrator); and the store
form claims the broker's rtlsdr-1, sdrplay-1 and libresdr-1 for them,
taking the serial or address the claim gives. No real radio and no real
library is opened here: the stand-in is named first, before any search."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import ctypes
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

from ham_helpers import close, make_radio, pump

from ohscore import host, sdr
from ohscore.devices import DeviceError
from ohscore.devices.sdrsource import RtlSdrDevice, SdrplayDevice, availability

STUB_C = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static char logbuf[65536]; static size_t loglen = 0;
static int dev_token = 42;
static const int gains[] = {0, 9, 14, 27, 37, 77, 87, 125, 144, 157, 166, 197, 207, 229, 254, 280, 297, 328,
                            338, 364, 372, 386, 402, 421, 434, 439, 445, 480, 496};
static void logf_(const char *name, long v) {
    int n = snprintf(logbuf + loglen, sizeof logbuf - loglen, "%s %ld\n", name, v);
    if (n > 0 && loglen + n < sizeof logbuf) loglen += n;
}
const char *stub_log(void) { logbuf[loglen] = 0; return logbuf; }
uint32_t rtlsdr_get_device_count(void) { return 1; }
const char *rtlsdr_get_device_name(uint32_t i) { return "Generic RTL2832U OEM"; }
int rtlsdr_get_device_usb_strings(uint32_t i, char *m, char *p, char *s) {
    strcpy(m, "Realtek"); strcpy(p, "RTL2838UHIDIR"); strcpy(s, "00000001"); return 0;
}
int rtlsdr_open(void **dev, uint32_t index) { logf_("open", index); *dev = &dev_token; return 0; }
int rtlsdr_close(void *dev) { logf_("close", 1); return 0; }
static uint32_t freq = 0, rate = 0;
int rtlsdr_set_center_freq(void *dev, uint32_t f) { logf_("freq", f); freq = f; return 0; }
uint32_t rtlsdr_get_center_freq(void *dev) { return freq; }
int rtlsdr_set_freq_correction(void *dev, int ppm) { return 0; }
int rtlsdr_set_sample_rate(void *dev, uint32_t r) { logf_("rate", r); rate = r; return 0; }
uint32_t rtlsdr_get_sample_rate(void *dev) { return rate; }
int rtlsdr_get_tuner_gains(void *dev, int *g) {
    int n = sizeof gains / sizeof gains[0]; if (g) memcpy(g, gains, sizeof gains); return n;
}
int rtlsdr_set_tuner_gain_mode(void *dev, int manual) { logf_("gain_mode", manual); return 0; }
int rtlsdr_set_tuner_gain(void *dev, int g) { logf_("gain", g); return 0; }
int rtlsdr_set_agc_mode(void *dev, int on) { logf_("agc", on); return 0; }
int rtlsdr_reset_buffer(void *dev) { return 0; }
/* A tone a quarter of the way up the band, at about -20 dBFS. */
static long n_out = 0;
int rtlsdr_read_sync(void *dev, void *buf, int len, int *n_read) {
    unsigned char *b = buf;
    for (int i = 0; i + 1 < len; i += 2, n_out++) {
        double ph = 6.283185307179586 * 0.25 * (double)n_out;
        b[i] = (unsigned char)(127.5 + 12.0 * __builtin_cos(ph));
        b[i + 1] = (unsigned char)(127.5 + 12.0 * __builtin_sin(ph));
    }
    *n_read = len;
    return 0;
}
"""


def _stub_rtlsdr(folder: str) -> str | None:
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        return None
    src = os.path.join(folder, "stub_rtlsdr.c")
    lib = os.path.join(folder, "librtlsdr-stub.so")
    with open(src, "w") as f:
        f.write(STUB_C)
    subprocess.run([cc, "-shared", "-fPIC", "-O1", "-o", lib, src, "-lm"], check=True)
    return lib


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class RtlSdrThroughTheEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.lib = _stub_rtlsdr(cls.tmp.name)
        if cls.lib is None:
            raise unittest.SkipTest("no C compiler for the stand-in librtlsdr")
        cls.ctl = ctypes.CDLL(cls.lib)
        cls.ctl.stub_log.restype = ctypes.c_char_p

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"SHACK_RTLSDR_LIB": self.lib})
        patcher.start()
        self.addCleanup(patcher.stop)

    def log(self):
        return self.ctl.stub_log().decode().split("\n")

    def test_the_engine_receives_tunes_and_never_keys(self):
        r = make_radio(device="rtlsdr", sampleRate=2_400_000, vfo=145_500_000.0, mode="fm",
                       rxGainMode="manual", rxGain=30.0, licenceClass="full")
        r.start()
        try:
            st = r.state()
            self.assertTrue(st["running"], st["error"])
            self.assertFalse(st["canTx"])
            self.assertEqual(st["fs"], 2_400_000.0)
            pump(r, 5, until=lambda: r.state()["deviceStatus"].get("blocks", 0) > 5)
            self.assertEqual(r.state()["deviceStatus"]["kind"], "rtlsdr")
            self.assertGreater(r.state()["deviceStatus"].get("blocks", 0), 5)
            log = self.log()
            self.assertIn("rate 2400000", log)
            self.assertIn("gain_mode 1", log)        # manual: the nearest tuner step to 30 dB
            self.assertIn("gain 297", log)
            tuned = [int(x.split()[1]) for x in log if x.startswith("freq ")]
            self.assertTrue(any(abs(f - 145_500_000) < 1_200_000 for f in tuned), tuned)
            with self.assertRaises(ValueError) as cm:
                r.ptt(True)
            self.assertIn("This radio can only receive", str(cm.exception))
            self.assertFalse(r.state()["keyed"])
        finally:
            close(r)
        self.assertIn("close 1", self.log())

    def test_automatic_gain_is_the_tuners_own(self):
        dev = RtlSdrDevice({"rxGainMode": "slow_attack", "rxGain": 30.0}, 1_200_000.0)
        dev.open()
        try:
            dev.set_rx_if(14_000_000.0)
            self.assertEqual(len(dev.read(10_000)), 10_000)
        finally:
            dev.close()
        log = self.log()
        self.assertIn("gain_mode 0", log)
        self.assertIn("agc 0", log)                  # the RTL2832's own AGC stays off: it pumps
        self.assertIn("rate 1200000", log)

    def test_antenna_is_rx_and_reported_the_soapy_shape_of_status(self):
        """An RTL-SDR has one socket (ohs-libs shack_sdr README): `status`
        still carries antenna/antennas, so Settings' drop-down and the API
        see the same shape it gets from a SoapyDevice (docs/SERVER-API.md)."""
        dev = RtlSdrDevice({"soapyAntenna": "RX"}, 1_200_000.0)
        dev.open()
        try:
            st = dev.status()
            self.assertEqual(st["antenna"], "RX")
            self.assertEqual(st["antennas"], ["RX"])
        finally:
            dev.close()

    def test_a_saved_antenna_this_receiver_does_not_have_fails_the_open(self):
        """Mirrors soapy.py's open(): an unknown `soapyAntenna` fails the
        whole open rather than listening on the wrong (only) input with
        nothing said - and the half-opened device is closed again, not
        left dangling."""
        dev = RtlSdrDevice({"soapyAntenna": "Antenna A"}, 1_200_000.0)
        with self.assertRaises(DeviceError) as cm:
            dev.open()
        self.assertIn("no such antenna", str(cm.exception))
        self.assertIn("close 1", self.log())

    def test_a_live_switch_to_an_unknown_input_is_refused_not_applied(self):
        dev = RtlSdrDevice({}, 1_200_000.0)
        dev.open()
        try:
            with self.assertRaises(DeviceError) as cm:
                dev.set_antenna("Antenna A")
            self.assertIn("no such antenna", str(cm.exception))
            self.assertEqual(dev.status()["antenna"], "RX")   # refused, so unchanged
        finally:
            dev.close()

    def test_empty_antenna_is_the_drivers_default_and_a_no_op_live(self):
        """"" means "the driver's default" (ohscore/antennas.py), already
        applied at open; set_antenna("") must never ask the source for an
        antenna it was never given - RtlSdrSource.set_antenna("") would
        refuse it (not one of ["RX"])."""
        dev = RtlSdrDevice({}, 1_200_000.0)
        dev.open()
        try:
            dev.set_antenna("")          # must not raise
            self.assertEqual(dev.status()["antenna"], "RX")
        finally:
            dev.close()


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class SdrplayWithoutTheApi(unittest.TestCase):
    def no_api(self):
        from shack_sdr.sources import sdrplay
        return mock.patch.multiple(sdrplay, DEFAULT_PLACES=[], LIB_PLACES={}), \
            mock.patch.object(sdrplay.ctypes.util, "find_library", lambda name: None), \
            mock.patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                         if k not in ("SHACK_SDRPLAY_LIB", "SHACK_HOSTLIBS")}, clear=True)

    def test_the_desktop_says_install_sdrplays_api(self):
        a, b, c = self.no_api()
        with a, b, c:
            ok, why = availability("sdrplay")
            self.assertFalse(ok)
            self.assertIn("Install SDRplay's API", why)
            dev = SdrplayDevice({}, 2_400_000.0)
            with self.assertRaises(DeviceError) as cm:
                dev.open()
            self.assertIn("Install SDRplay's API to use this radio", str(cm.exception))

    def test_a_controller_says_ask_the_administrator(self):
        # A controller that lends host libraries (SHACK_HOSTLIBS set) but
        # whose administrator has not installed sdrplay-api.
        a, b, c = self.no_api()
        with a, b, c, mock.patch.object(host, "STORE", True), tempfile.TemporaryDirectory() as libs, \
                mock.patch.dict(os.environ, {"SHACK_HOSTLIBS": libs}):
            ok, why = availability("sdrplay")
            self.assertFalse(ok)
            self.assertIn("Ask your controller's administrator to install SDRplay's API", why)

    def test_a_controller_too_old_for_host_libraries_says_update_it(self):
        # No SHACK_HOSTLIBS in the store form: the controller ignored the
        # manifest's host_libraries, and nothing an administrator installs
        # would reach the app.
        a, b, c = self.no_api()
        with a, b, c, mock.patch.object(host, "STORE", True):
            ok, why = availability("sdrplay")
            self.assertFalse(ok)
            self.assertEqual(why, "Update the controller to use SDRplay radios and DAB+")
            dev = SdrplayDevice({}, 2_400_000.0)
            with self.assertRaises(DeviceError) as cm:
                dev.open()
            self.assertEqual(str(cm.exception), "Update the controller to use SDRplay radios and DAB+")

    def test_an_rsp_offers_only_2_4_ms(self):
        dev = SdrplayDevice({}, 1_200_000.0)
        self.assertEqual(dev.fs, 2_400_000.0)
        self.assertIn("2.4 MS/s", dev.status()["notes"][0])

    def test_manual_gain_is_a_reduction_held_to_sdrplays_range(self):
        dev = SdrplayDevice({}, 2_400_000.0)
        self.assertIsNone(dev._gain("slow_attack", 40.0))
        self.assertEqual(dev._gain("manual", 40.0), 39.0)
        self.assertEqual(dev._gain("manual", 0.0), 59.0)
        self.assertEqual(dev._gain("manual", 73.0), 20.0)


class FakeSdrplaySource:
    """Just enough of SdrplaySource's shape (ohs-libs shack_sdr README
    "Antenna/input selection") to drive SdrplayDevice's antenna code
    without the SDRplay API or real hardware: an RSPdx's three inputs,
    resolved at open() the way the real source resolves them against the
    model it found, and switched live after that."""

    ANTENNAS = ("Antenna A", "Antenna B", "Antenna C")

    def __init__(self, centre, rate, gain, *, serial=None, lna_state=4, antenna=None):
        self.centre, self.rate, self.gain = centre, rate, gain
        self.serial, self.lna_state = serial, lna_state
        self.antenna = antenna
        self.opened = False
        self.switches: list[str] = []

    def open(self) -> None:
        from shack_sdr.sources import SdrError
        if self.antenna is None:
            self.antenna = self.ANTENNAS[0]
        elif self.antenna not in self.ANTENNAS:
            raise SdrError("bad-antenna",
                           f"{self.antenna!r} is not one of this receiver's inputs: {list(self.ANTENNAS)}")
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def antennas(self) -> list[str]:
        return list(self.ANTENNAS) if self.opened else []

    def set_antenna(self, name: str) -> None:
        from shack_sdr.sources import SdrError
        names = self.antennas()
        if name not in names:
            raise SdrError("bad-antenna", f"{name!r} is not one of this receiver's inputs: {names}")
        self.switches.append(name)
        self.antenna = name

    def set_centre(self, hz: float) -> None:
        self.centre = hz

    def set_gain(self, gain) -> None:
        self.gain = gain

    def read(self):
        from shack_sdr.sources import IqBlock
        return IqBlock(np.zeros(1024, np.complex64), 0, 0.0, 0)

    def status(self) -> dict:
        return {"kind": "sdrplay", "centre": self.centre, "rate": self.rate, "gain": self.gain,
                "antenna": self.antenna, "antennas": self.antennas(), "open": self.opened,
                "blocks": 0, "samples": 0, "dropped": 0, "drops": 0, "lagS": 0.0, "notes": []}


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class SdrplayAntennaThroughAFakeSource(unittest.TestCase):
    """SdrplaySource's own antenna switching is proven in ohs-libs against
    the SDRplay API's own fixtures; what RADIO-SDR-PLAN needs checked here
    is sdrsource.py's side of the contract - the saved `soapyAntenna`
    reaching the source's constructor, an unknown one failing the open,
    and the engine's live switch reaching `set_antenna` - against a fake
    standing in for SdrplaySource (no SDRplay API is reachable from a
    test host)."""

    def dev(self, cfg):
        with mock.patch("shack_sdr.sources.SdrplaySource", FakeSdrplaySource):
            d = SdrplayDevice(dict(cfg), 2_400_000.0)
            d.open()
        return d

    def test_the_saved_antenna_is_given_to_the_source_at_open(self):
        dev = self.dev({"soapyAntenna": "Antenna C"})
        try:
            self.assertEqual(dev.src.antenna, "Antenna C")
            self.assertEqual(dev.status()["antenna"], "Antenna C")
            self.assertEqual(dev.status()["antennas"], ["Antenna A", "Antenna B", "Antenna C"])
            self.assertEqual(dev.src.switches, [])    # given at construction, not a live switch
        finally:
            dev.close()

    def test_no_saved_antenna_opens_on_the_models_default(self):
        dev = self.dev({})
        try:
            self.assertEqual(dev.src.antenna, "Antenna A")
        finally:
            dev.close()

    def test_an_unknown_saved_antenna_fails_the_open_and_closes_the_source(self):
        with mock.patch("shack_sdr.sources.SdrplaySource", FakeSdrplaySource):
            d = SdrplayDevice({"soapyAntenna": "Antenna Z"}, 2_400_000.0)
            with self.assertRaises(DeviceError) as cm:
                d.open()
        self.assertIn("no such antenna", str(cm.exception))
        self.assertIsNone(d.src)

    def test_a_live_switch_reaches_the_source_and_an_unknown_one_is_refused(self):
        dev = self.dev({})
        try:
            dev.set_antenna("Antenna B")
            self.assertEqual(dev.src.antenna, "Antenna B")
            self.assertEqual(dev.src.switches, ["Antenna B"])
            with self.assertRaises(DeviceError) as cm:
                dev.set_antenna("Antenna Z")
            self.assertIn("no such antenna", str(cm.exception))
            self.assertEqual(dev.src.antenna, "Antenna B")     # refused, so unchanged
        finally:
            dev.close()


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class SoapySdrplayWithoutSoapySDRPlay3(unittest.TestCase):
    """`device` soapy with driver=sdrplay (ohs-box's RSPdx, set up when the
    image carried SoapySDRPlay3) where SoapySDR has no SDRplay module -
    Radio's store image since it stopped carrying SDRplay's files: the
    same RSP through shack_sdr's binding, its soapyArgs understood."""

    ARGS = "driver=sdrplay,serial=240309F070,rfgain_sel=4"

    def make(self, cfg, module: bool):
        from ohscore.devices import registry
        with mock.patch("ohscore.devices.sdrsource.soapy_has_driver", lambda d: module):
            return registry.DeviceRegistry().make({"device": "soapy", "sampleRate": 2_400_000, **cfg})

    def test_without_the_module_the_rsp_opens_through_the_sdrplay_api(self):
        with mock.patch("shack_sdr.sources.SdrplaySource", FakeSdrplaySource):
            dev = self.make({"soapyArgs": self.ARGS, "soapyAntenna": "Antenna C"}, module=False)
            dev.open()
        try:
            self.assertEqual(dev.kind, "soapy")              # the station's settings and claim are unchanged
            self.assertFalse(dev.can_tx)
            self.assertEqual((dev.src.serial, dev.src.lna_state, dev.src.antenna), ("240309F070", 4, "Antenna C"))
            self.assertEqual(dev.fs, 2_400_000.0)
            st = dev.status()
            self.assertEqual((st["kind"], st["via"], st["antenna"]), ("soapy", "sdrplay-api", "Antenna C"))
            dev.set_rx_if(222_064_000.0)
            self.assertEqual(dev.src.centre, 222_064_000.0)
            self.assertEqual(len(dev.read(512)), 512)
        finally:
            dev.close()

    def test_without_the_api_it_names_sdrplays_api(self):
        a, b, c = SdrplayWithoutTheApi.no_api(self)
        with a, b, c, mock.patch.object(host, "STORE", True):
            dev = self.make({"soapyArgs": self.ARGS}, module=False)
            with self.assertRaises(DeviceError) as cm:
                dev.open()
        self.assertEqual(str(cm.exception), "Update the controller to use SDRplay radios and DAB+")

    def test_with_the_module_soapysdr_opens_it_as_before(self):
        from ohscore.devices.soapy import SoapyDevice
        dev = self.make({"soapyArgs": self.ARGS}, module=True)
        self.assertIsInstance(dev, SoapyDevice)

    def test_another_soapysdr_driver_is_left_to_soapysdr(self):
        from ohscore.devices.soapy import SoapyDevice
        self.assertIsInstance(self.make({"soapyArgs": "driver=rtlsdr"}, module=False), SoapyDevice)

    def test_the_module_is_recognised_by_its_file_name(self):
        from ohscore.devices import sdrsource
        fake = mock.MagicMock()
        fake.listModules.return_value = ("/usr/lib/x86_64-linux-gnu/SoapySDR/modules0.8/librtlsdrSupport.so",)
        with mock.patch.dict("sys.modules", {"SoapySDR": fake}):
            self.assertFalse(sdrsource.soapy_has_driver("sdrplay"))
            fake.listModules.return_value += ("/usr/lib/x86_64-linux-gnu/SoapySDR/modules0.8/libsdrPlaySupport.so",)
            self.assertTrue(sdrsource.soapy_has_driver("sdrplay"))


class StoreClaims(unittest.TestCase):
    """The store form claims the broker device for each kind, and takes the
    serial (USB) or address (network) the claim gives."""

    def serve(self, device, access):
        from ohscore.server import shack
        from ohscore.server.app import Server
        from ohscore.server.audio import StreamAudio
        from ohsradio import server as ham_server
        from ohsradio.devices.sim import HamSim
        from ohsradio.radio import Radio
        from test_server import SECRET, FakeBroker

        class Receiver(HamSim):
            can_tx = device not in ("rtlsdr", "sdrplay")

        class Broker(FakeBroker):
            def __call__(self, method, path, body=None, headers=None):
                status, answer = super().__call__(method, path, body, headers)
                if method == "POST" and path == "/broker/claims" and status == 201:
                    answer["access"] = dict(access)
                return status, answer

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": device, "audioBackend": "null", "simRealtime": False, "simSeed": 7,
               "callsign": "GM4BRI", "licenceClass": "full", "vfo": 14_070_000.0, "mode": "usb"}
        audio = StreamAudio(realtime=False)
        radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio, device=Receiver(dict(cfg), 2_400_000.0))
        fake = Broker()
        srv = Server(radio, ham_server.info("9.9.9"), audio, secret=SECRET, broker=shack.BrokerClient(fake))
        srv.serve("127.0.0.1", 0)
        self.addCleanup(srv.shutdown)
        self.assertEqual(srv.start_radio(), "")
        return srv, radio, fake

    def test_an_rtl_sdr_is_rtlsdr_1_and_the_claims_serial_picks_it(self):
        srv, radio, fake = self.serve("rtlsdr", {"reach": "usb", "usbId": "0bda:2838", "serial": "00000001"})
        self.assertEqual(srv.device(), "rtlsdr-1")
        self.assertEqual([(b["device"], b["mode"]) for b in fake.claim_bodies()], [("rtlsdr-1", "rx")])
        self.assertEqual(radio.st["sdrSerial"], "00000001")
        self.assertEqual(srv.key("tv-1", "brian"), "This radio can only receive")
        srv.stop_radio()
        self.assertTrue([p for m, p, _b, _h in fake.calls if m == "DELETE" and "/broker/claims/" in p])

    def test_an_rsp_through_shack_sdr_is_sdrplay_1_and_a_bad_serial_is_ignored(self):
        srv, radio, fake = self.serve("sdrplay", {"reach": "usb", "usbId": "1df7:3030", "serial": "x;rm -rf"})
        self.assertEqual(srv.device(), "sdrplay-1")
        self.assertEqual(radio.st["sdrSerial"], "")

    def test_a_libresdr_is_libresdr_1_at_the_address_the_claim_gives(self):
        srv, radio, fake = self.serve("libresdr", {"reach": "network", "address": "198.51.100.10"})
        self.assertEqual(srv.device(), "libresdr-1")
        self.assertEqual(radio.st["plutoUri"], "ip:198.51.100.10")


if __name__ == "__main__":
    unittest.main()
