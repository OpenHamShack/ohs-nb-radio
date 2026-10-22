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
        a, b, c = self.no_api()
        with a, b, c, mock.patch.object(host, "STORE", True):
            ok, why = availability("sdrplay")
            self.assertFalse(ok)
            self.assertIn("Ask your controller's administrator to install SDRplay's API", why)

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
