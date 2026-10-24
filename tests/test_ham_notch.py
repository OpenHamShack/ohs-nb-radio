"""The SDRplay RSP's front-end notches, `dabNotch` and `rfNotch`
(ohsradio/notch.py; Brian, 24/10/2026: the Ayr DAB transmitter, 8 km away
on block 11B, overloads the RSPdx on 2 m).

Run through the real thing wherever it can be: Radio's engine opening
shack_sdr's own SdrplaySource over a stand-in SDRplay API compiled
against SDRplay's headers (as tests/test_sdr_receivers.py does for the
gain), which logs each Init and Update with the notch fields as the
API's structures hold them. So what is checked is what SDRplay's service
would be handed, field by field, not what Radio meant to send.

- **Automatic** at 145 MHz puts both in on an RSPdx; tuned to 218.640 MHz
  (11B) the DAB notch comes out and the broadcast notch stays in.
- **On and off** hold a notch wherever the receiver is tuned.
- **Live:** a retune or a changed setting is one Update on the running
  stream, never a second Init; a reopen comes back with what was applied.
- **Per model:** an RSP2 is only offered the broadcast notch, an RSP1
  neither; `deviceStatus.options` reads back what the model has.
- **Nothing else is touched:** the simulator, and any device without a
  notch, is never asked; SoapySDR with SoapySDRPlay3 writes its own keys.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import ctypes
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from ham_helpers import close, make_radio, pump

from ohscore import sdr
from ohsradio import notch

SDRPLAY_INCLUDE = os.environ.get("SHACK_SDRPLAY_INCLUDE", "/usr/local/include")

# The stand-in: SelectDevice zeroes the structures (SDRplay's defaults for
# these fields are 0, notches out); every Init and Update logs, by the
# headers' own names, the RSPdx/RSP1A device-level notch fields and the
# RSP2 channel-level one, with the reasons the Update carried.
STUB = r"""
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
#include "sdrplay_api.h"
static sdrplay_api_DevParamsT dev;
static sdrplay_api_RxChannelParamsT chA, chB;
static sdrplay_api_DeviceParamsT params = {&dev, &chA, &chB};
static sdrplay_api_CallbackFnsT cbs;
static int running, locked, hwver = SDRPLAY_RSPdx_ID, token = 5;
static pthread_t th;
static char logbuf[65536]; static size_t loglen = 0;
static void note(const char *what, int reason, int ext) {
    int n = snprintf(logbuf + loglen, sizeof logbuf - loglen,
                     "%s reason=%d ext=%d dx_rf=%d dx_dab=%d a_rf=%d a_dab=%d rsp2_rf=%d rfhz=%d\n",
                     what, reason, ext, dev.rspDxParams.rfNotchEnable, dev.rspDxParams.rfDabNotchEnable,
                     dev.rsp1aParams.rfNotchEnable, dev.rsp1aParams.rfDabNotchEnable,
                     chA.rsp2TunerParams.rfNotchEnable, (int)(chA.tunerParams.rfFreq.rfHz / 1000));
    if (n > 0 && loglen + n < sizeof logbuf) loglen += n;
}
const char *stub_log(void) { logbuf[loglen] = 0; return logbuf; }
void stub_clear(void) { loglen = 0; }
void stub_set_hwver(int v) { hwver = v; }
static void *pump(void *a) {
    enum { N = 1344 };
    static short z[N];
    struct timespec ts = {0, 5000000}, t0, t;
    sdrplay_api_StreamCbParamsT p; memset(&p, 0, sizeof p);
    long sent = 0;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    while (running) {
        clock_gettime(CLOCK_MONOTONIC, &t);
        double due = ((t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) * 1e-9) * dev.fsFreq.fsHz;
        while (running && sent < due) { cbs.StreamACbFn(z, z, &p, N, 0, 0); sent += N; }
        nanosleep(&ts, 0);
    }
    return 0;
}
sdrplay_api_ErrT sdrplay_api_Open(void) { return sdrplay_api_Success; }
sdrplay_api_ErrT sdrplay_api_Close(void) { return sdrplay_api_Success; }
sdrplay_api_ErrT sdrplay_api_ApiVersion(float *v) { *v = SDRPLAY_API_VERSION; return sdrplay_api_Success; }
sdrplay_api_ErrT sdrplay_api_LockDeviceApi(void) { locked = 1; return sdrplay_api_Success; }
sdrplay_api_ErrT sdrplay_api_UnlockDeviceApi(void) { locked = 0; return sdrplay_api_Success; }
sdrplay_api_ErrT sdrplay_api_GetDevices(sdrplay_api_DeviceT *d, unsigned int *n, unsigned int max) {
    *n = 1; memset(d, 0, sizeof *d); snprintf(d->SerNo, 64, "240309F070"); d->hwVer = hwver; d->valid = 1;
    d->dev = &token; return sdrplay_api_Success;
}
sdrplay_api_ErrT sdrplay_api_SelectDevice(sdrplay_api_DeviceT *d) {
    if (!locked) return sdrplay_api_Fail;
    memset(&dev, 0, sizeof dev); memset(&chA, 0, sizeof chA); memset(&chB, 0, sizeof chB);
    dev.fsFreq.fsHz = 2e6;
    chA.tunerParams.gain.gRdB = chB.tunerParams.gain.gRdB = 50;
    return sdrplay_api_Success;
}
sdrplay_api_ErrT sdrplay_api_ReleaseDevice(sdrplay_api_DeviceT *d) { return sdrplay_api_Success; }
const char *sdrplay_api_GetErrorString(sdrplay_api_ErrT e) { return "stub error"; }
sdrplay_api_ErrT sdrplay_api_GetDeviceParams(HANDLE h, sdrplay_api_DeviceParamsT **p) { *p = &params; return sdrplay_api_Success; }
sdrplay_api_ErrT sdrplay_api_Init(HANDLE h, sdrplay_api_CallbackFnsT *c, void *ctx) {
    cbs = *c; note("init", 0, 0); running = 1; pthread_create(&th, 0, pump, 0); return sdrplay_api_Success;
}
sdrplay_api_ErrT sdrplay_api_Uninit(HANDLE h) { if (running) { running = 0; pthread_join(th, 0); } return sdrplay_api_Success; }
sdrplay_api_ErrT sdrplay_api_Update(HANDLE h, sdrplay_api_TunerSelectT t, sdrplay_api_ReasonForUpdateT r,
                                    sdrplay_api_ReasonForUpdateExtension1T e) {
    note("update", (int)r, (int)e); return sdrplay_api_Success;
}
sdrplay_api_ErrT sdrplay_api_SwapRspDuoActiveTuner(HANDLE h, sdrplay_api_TunerSelectT *t,
                                                    sdrplay_api_RspDuo_AmPortSelectT p) { return sdrplay_api_Success; }
"""

# sdrplay_api.h: the RSPdx's notches are extension-1 reasons, the others'
# plain ones.
EXT1_RSPDX_RF_NOTCH, EXT1_RSPDX_DAB_NOTCH = 0x8, 0x10
UPDATE_RSP2_RF_NOTCH = 0x400
HW_RSP1, HW_RSP2, HW_RSPDX = 1, 2, 4

MHZ = 1e6


class TheRule(unittest.TestCase):
    """notch.wanted on numbers alone, for a 2.4 MS/s span."""

    def at(self, hz, dab="auto", rf="auto", held=False):
        return notch.wanted(dab, rf, hz - 1.2 * MHZ, hz + 1.2 * MHZ, dab_held=held)

    def test_automatic_puts_both_in_on_2_m_and_takes_the_dab_notch_out_on_11b(self):
        self.assertEqual(self.at(145 * MHZ), {"dab_notch": True, "rf_notch": True})
        self.assertEqual(self.at(218.640 * MHZ), {"dab_notch": False, "rf_notch": True})

    def test_band_iii_edges_and_a_span_that_only_overlaps_one(self):
        self.assertFalse(self.at(174.5 * MHZ)["dab_notch"])         # the span reaches over 174
        self.assertTrue(self.at(172.5 * MHZ)["dab_notch"])          # wholly below it
        self.assertFalse(self.at(240.9 * MHZ)["dab_notch"])
        self.assertTrue(self.at(242 * MHZ)["dab_notch"])

    def test_a_dab_session_takes_it_out_wherever_the_centre_is(self):
        self.assertFalse(self.at(145 * MHZ, held=True)["dab_notch"])

    def test_the_broadcast_notch_comes_out_for_fm_and_am_broadcasting_only(self):
        for hz in (88.0 * MHZ, 98.5 * MHZ, 107.9 * MHZ, 0.909 * MHZ, 0.198 * MHZ):
            with self.subTest(MHz=hz / MHZ):
                self.assertFalse(self.at(hz)["rf_notch"])
        # 160 m, 80 m, 6 m, 4 m, airband: in.
        for hz in (3.65 * MHZ, 50.2 * MHZ, 70.2 * MHZ, 118 * MHZ):
            with self.subTest(MHz=hz / MHZ):
                self.assertTrue(self.at(hz)["rf_notch"])
        # A span wholly between MW and 160 m is clear of both.
        self.assertTrue(notch.wanted("auto", "auto", 1.71 * MHZ, 2.0 * MHZ)["rf_notch"])

    def test_on_and_off_hold_whatever_is_tuned(self):
        self.assertEqual(self.at(218.640 * MHZ, dab="on", rf="off"), {"dab_notch": True, "rf_notch": False})
        self.assertEqual(self.at(145 * MHZ, dab="off", rf="off"), {"dab_notch": False, "rf_notch": False})
        self.assertEqual(self.at(98 * MHZ, dab="on", rf="on", held=True), {"dab_notch": True, "rf_notch": True})


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class NotchesThroughTheApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc") or shutil.which("gcc")
        if cc is None:
            raise unittest.SkipTest("no C compiler for the stand-in SDRplay API")
        if not os.path.exists(os.path.join(SDRPLAY_INCLUDE, "sdrplay_api.h")):
            raise unittest.SkipTest("SDRplay's API headers are not installed here")
        cls.tmp = tempfile.TemporaryDirectory()
        src = os.path.join(cls.tmp.name, "stub_sdrplay.c")
        cls.lib = os.path.join(cls.tmp.name, "libsdrplay_api_notch_stub.so")
        with open(src, "w") as f:
            f.write(STUB)
        subprocess.run([cc, "-shared", "-fPIC", "-O1", "-pthread", f"-I{SDRPLAY_INCLUDE}", "-o", cls.lib, src],
                       check=True)
        cls.ctl = ctypes.CDLL(cls.lib)
        cls.ctl.stub_log.restype = ctypes.c_char_p

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        p = mock.patch.dict(os.environ, {"SHACK_SDRPLAY_LIB": self.lib})
        p.start()
        self.addCleanup(p.stop)
        self.ctl.stub_clear()
        self.ctl.stub_set_hwver(HW_RSPDX)

    def log(self) -> list[dict]:
        out = []
        for line in self.ctl.stub_log().decode().splitlines():
            what, *kv = line.split()
            out.append({"what": what, **{k: int(v) for k, v in (x.split("=") for x in kv)}})
        return out

    def inits(self) -> int:
        return sum(1 for e in self.log() if e["what"] == "init")

    def radio(self, **cfg):
        r = make_radio(device="sdrplay", sampleRate=2_400_000, vfo=145_500_000.0, mode="fm",
                       rxGainMode="manual", rxGain=40.0, licenceClass="full", **cfg)
        r.start()
        self.addCleanup(close, r)
        st = r.state()
        self.assertTrue(st["running"], st["error"])
        return r

    def options(self, r, want: dict) -> dict:
        """deviceStatus.options once it says `want` (or after 5 s)."""
        pump(r, 5, until=lambda: {k: r.state()["deviceStatus"].get("options", {}).get(k) for k in want} == want)
        return r.state()["deviceStatus"].get("options", {})

    def test_automatic_on_2_m_then_11b_on_an_rspdx(self):
        r = self.radio()
        self.assertEqual(self.options(r, {"dab_notch": True, "rf_notch": True}),
                         {"dab_notch": True, "rf_notch": True, "bias_t": False, "hdr": False})
        last = self.log()[-1]
        self.assertEqual((last["dx_dab"], last["dx_rf"]), (1, 1))
        # Block 11B: the DAB notch comes out on its own, the broadcast one stays.
        r.set(vfo=218_640_000.0)
        self.assertEqual(self.options(r, {"dab_notch": False}), {"dab_notch": False, "rf_notch": True,
                                                                  "bias_t": False, "hdr": False})
        last = self.log()[-1]
        self.assertEqual((last["what"], last["ext"], last["dx_dab"], last["dx_rf"]),
                         ("update", EXT1_RSPDX_DAB_NOTCH, 0, 1))
        # ...and back on 2 m it goes in again.
        r.set(vfo=145_500_000.0)
        self.assertEqual(self.options(r, {"dab_notch": True})["dab_notch"], True)
        # Each change was an Update on the running stream: one Init, ever.
        self.assertEqual(self.inits(), 1)

    def test_on_and_off_override_live_with_no_reopen(self):
        r = self.radio()
        self.options(r, {"dab_notch": True, "rf_notch": True})
        src = r.dev.src
        self.ctl.stub_clear()
        r.set(dabNotch="off", rfNotch="off")
        self.assertEqual(self.options(r, {"dab_notch": False, "rf_notch": False})["rf_notch"], False)
        ups = self.log()
        self.assertEqual(sorted(e["ext"] for e in ups), [EXT1_RSPDX_RF_NOTCH, EXT1_RSPDX_DAB_NOTCH])
        self.assertEqual((ups[-1]["dx_dab"], ups[-1]["dx_rf"]), (0, 0))
        self.assertEqual(self.inits(), 0)
        self.assertIs(r.dev.src, src)                          # the same open source: never reopened
        # On holds the DAB notch in on 11B, where automatic would take it out.
        r.set(dabNotch="on", vfo=218_640_000.0)
        self.assertTrue(self.options(r, {"dab_notch": True})["dab_notch"])
        pump(r, 0.5)
        self.assertTrue(r.state()["deviceStatus"]["options"]["dab_notch"])
        self.assertEqual(r.state()["dabNotch"], "on")

    def test_a_reopen_comes_back_with_the_notches_applied(self):
        # What the engine's reconnect does (Engine._device_lost): close,
        # open, re-tune, and nothing else.
        r = self.radio(dabNotch="off")
        self.options(r, {"dab_notch": False, "rf_notch": True})
        self.ctl.stub_clear()
        r.dev.close()
        r.dev.open()
        first = self.log()[0]
        self.assertEqual((first["what"], first["dx_dab"], first["dx_rf"]), ("init", 0, 1))

    def test_an_rsp2_is_offered_the_broadcast_notch_alone(self):
        self.ctl.stub_set_hwver(HW_RSP2)
        r = self.radio()
        opts = self.options(r, {"rf_notch": True})
        self.assertNotIn("dab_notch", opts)
        self.assertEqual(r.dev.notches(), ("rf_notch",))
        ups = [e for e in self.log() if e["what"] == "update" and e["reason"] & UPDATE_RSP2_RF_NOTCH]
        self.assertEqual(ups[-1]["rsp2_rf"], 1)

    def test_an_rsp1_has_none_and_is_never_asked(self):
        self.ctl.stub_set_hwver(HW_RSP1)
        r = self.radio(dabNotch="on", rfNotch="on")
        pump(r, 1)
        self.assertEqual(r.dev.notches(), ())
        self.assertEqual(r.dev.notch_want, {})
        self.assertFalse(r.state()["deviceStatus"].get("options"))
        self.assertFalse([e for e in self.log() if e["what"] == "update" and e["ext"] in
                          (EXT1_RSPDX_RF_NOTCH, EXT1_RSPDX_DAB_NOTCH)])


class NotForOtherRadios(unittest.TestCase):
    def test_the_simulator_is_never_asked_and_its_status_unchanged(self):
        from ohscore.devices.base import Device
        calls = []
        with mock.patch.object(Device, "set_notches", lambda self, **kw: calls.append(kw)):
            r = make_radio(dabNotch="on", rfNotch="on")
            r.start()
            try:
                pump(r, 1)
                r.set(dabNotch="off", vfo=218_640_000.0)
                pump(r, 1)
                self.assertEqual(r.dev.notches(), ())
                self.assertNotIn("options", r.state()["deviceStatus"])
            finally:
                close(r)
        self.assertEqual(calls, [])

    def test_the_settings_are_in_the_spec_as_auto_on_off(self):
        from ohsradio.state import REG
        for key in ("dabNotch", "rfNotch"):
            with self.subTest(key=key):
                k = REG.spec[key]
                self.assertEqual((k["default"], list(k["choices"]), k["restart"]),
                                 ("auto", ["auto", "on", "off"], False))
                with self.assertRaises(ValueError):
                    REG.coerce(key, "sometimes")


class SoapySdrplay3Notches(unittest.TestCase):
    """SoapySDR with SoapySDRPlay3 installed: the notches are its settings
    rfnotch_ctrl and dabnotch_ctrl, offered only where it lists them."""

    def dev(self, keys):
        from ohscore.devices.soapy import SoapyDevice
        d = SoapyDevice("driver=sdrplay")
        d.RX = 0
        d.sdr = mock.MagicMock()
        d.sdr.getSettingInfo.return_value = [mock.Mock(key=k) for k in keys]
        held = {}
        d.sdr.writeSetting.side_effect = lambda k, v: held.__setitem__(k, v)
        d.sdr.readSetting.side_effect = lambda k: held.get(k, "false")
        d.notch_names = d._list_notches()
        return d, held

    def test_writes_soapysdrplay3s_keys_and_reads_them_back(self):
        d, held = self.dev(["rfnotch_ctrl", "dabnotch_ctrl", "biasT_ctrl"])
        self.assertEqual(d.notches(), ("rf_notch", "dab_notch"))
        d.set_notches(rf_notch=True, dab_notch=False)
        self.assertEqual(held, {"rfnotch_ctrl": "true", "dabnotch_ctrl": "false"})
        self.assertEqual(d.status()["options"], {"rf_notch": True, "dab_notch": False})

    def test_another_driver_lists_neither_and_is_never_written(self):
        d, held = self.dev(["direct_samp", "offset_tune"])            # an RTL-SDR's
        self.assertEqual(d.notches(), ())
        d.set_notches(rf_notch=True)
        self.assertEqual(held, {})
        self.assertNotIn("options", d.status())


if __name__ == "__main__":
    unittest.main()
