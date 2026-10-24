"""Recordings of a broadcast station are named and described as the station
(ohscore/server/recording.py, host.recording_name, Radio.broadcast_station;
docs/SERVER-API.md "Recordings"), for the TV's DAB Radio and its Record
button:

- **DAB:** while a DAB session holds the receiver, an audio recording's
  mode is "DAB", its frequency the block's centre, its sidecar's
  `broadcast` the station (labels, SId, block, ensemble and EId,
  programme type, the text and DL Plus as it started), and its name the
  station's: `openhamshack-radio-<UTC>-Shack-MP2-Tone-DAB`. It is 48 kHz
  stereo FLAC, served for playing with ranges (206). An IQ recording of
  the same is the whole block, so it is named by the block and its
  frequency, and says DAB, not the operator's mode from before.
- **Wide FM:** the RDS name in the name and the sidecar, with PI and
  RadioText.
- **Anything else** is named by the dial and the mode as before, with the
  app's own name in front of both kinds.

On the RSPdx-shaped simulator with shack_sdr's showcase DAB ensemble on 11D
and its FM stereo and RDS transmitter on 88.6 MHz, over real HTTP. Receive
only: nothing here keys."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import re
import tempfile
import time
import unittest
from pathlib import Path

from ohscore import host, sdr, sigmf
from ohscore.server import shack
from ohscore.server.app import Server

from test_ham_audio48 import flac_rate_and_channels

SECRET = "s" * 32
CENTRE, FM = 222_064_000.0, 88_600_000.0
STAMP = r"\d{8}-\d{6}Z"


class Names(unittest.TestCase):
    """host.recording_name and filename_label on their own."""

    def test_a_station_name_made_safe(self):
        self.assertEqual(host.filename_label("BBC Radio 4"), "BBC-Radio-4")
        self.assertEqual(host.filename_label("Kåre's Hits & Möre!!"), "Kares-Hits-and-More")
        self.assertEqual(host.filename_label("  ***  "), "")
        self.assertEqual(host.filename_label(None), "")
        long = host.filename_label("A Station With A Name Far Longer Than Any Label Should Be")
        self.assertLessEqual(len(long), host.LABEL_MAX)
        self.assertFalse(long.endswith("-"))

    def test_each_kind_of_name(self):
        t = 1_792_815_588.0                                     # 2026-10-24 04:19:48 UTC
        dab = {"kind": "dab", "label": "BBC Radio 4", "block": "11B"}
        self.assertEqual(host.recording_name("openhamshack-radio", t, 218_640_000.0, "DAB", dab),
                         "openhamshack-radio-20261024-041948Z-BBC-Radio-4-DAB")
        self.assertEqual(host.recording_name("openhamshack-radio", t, 218_640_000.0, "DAB+", dab, iq=True),
                         "openhamshack-radio-20261024-041948Z-11B-218.640MHz-DABplus")
        # A DAB session listing the ensemble, playing nothing: the block.
        self.assertEqual(host.recording_name("openhamshack-radio", t, 218_640_000.0, "DAB",
                                             {"kind": "dab", "label": None, "block": "11B"}),
                         "openhamshack-radio-20261024-041948Z-11B-DAB")
        wfm = {"kind": "wfm", "label": "SIM ONE"}
        self.assertEqual(host.recording_name("openhamshack-radio", t, FM, "WFM", wfm),
                         "openhamshack-radio-20261024-041948Z-SIM-ONE-WFM")
        self.assertEqual(host.recording_name("openhamshack-radio", t, FM, "WFM", wfm, iq=True),
                         "openhamshack-radio-20261024-041948Z-88.600MHz-SIM-ONE-WFM")
        # Wide FM before its RDS is heard, and every other mode: as before.
        self.assertEqual(host.recording_name("openhamshack-radio", t, FM, "WFM", {"kind": "wfm", "label": None}),
                         "openhamshack-radio-20261024-041948Z-88.600000MHz-WFM")
        self.assertEqual(host.recording_name("openhamshack-nb", t, 10_489_750_000.0, "USB"),
                         "openhamshack-nb-20261024-041948Z-10489.750000MHz-USB")
        self.assertEqual(host.recording_name("openhamshack-nb", t, 10_489_750_000.0, "usb", iq=True),
                         "openhamshack-nb-20261024-041948Z-10489.750MHz-USB")


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class OverTheApi(unittest.TestCase):
    def setUp(self):
        from ohscore.server.audio import StreamAudio
        from ohsradio import server as ham_server
        from ohsradio.devices import simdab
        from ohsradio.devices.simfm import FmBand, FmStation
        from ohsradio.radio import Radio
        from listen_helpers import ListeningSim
        from shack_sdr import _native
        try:
            _native.testsig_dab(1, showcase_mjd=61_337)
        except TypeError:
            self.skipTest("shack_sdr without the showcase ensemble")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": 145_500_000.0,
               "mode": "fm"}
        self.audio = StreamAudio(realtime=False)
        dev = ListeningSim(dict(cfg), 2_400_000.0, [simdab.DabEnsemble("11D", -30.0)])
        dev.fm = FmBand([FmStation(FM, -15.0, 0xC201, "SIM ONE", "Sim One: 1 kHz left, 1.5 right", 10,
                                   True, 1000.0, 1500.0)])
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio, device=dev)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        self.port = self.srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def raw(self, method, path, body=None, headers=None, level="control"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "brian",
             "X-OpenHamShack-Level": level, "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device",
             **(headers or {})}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def req(self, method, path, body=None, level="control"):
        s, _h, data = self.raw(method, path, body, level=level)
        return s, json.loads(data)

    def wait(self, cond, timeout=90.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.radio.heartbeat()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def record(self, *kinds, seconds=1.0):
        """Record `kinds` together for `seconds`; their entries in the list."""
        for kind in kinds:
            s, a = self.req("POST", "/api/recordings/start", {"kind": kind})
            self.assertEqual(s, 200, a)
        self.assertTrue(self.wait(lambda: all(
            any(x["kind"] == k and x["seconds"] >= seconds for x in self.req("GET", "/api/recordings/status")[1]["active"])
            for k in kinds)))
        s, a = self.req("POST", "/api/recordings/stop", {})
        ids = {x["kind"]: x["id"] for x in a["stopped"]}
        listed = {x["id"]: x for x in self.req("GET", "/api/recordings", level="view")[1]["recordings"]}
        return [listed[ids[k]] for k in kinds]

    def sidecar(self, e):
        s, _h, data = self.raw("GET", f"/api/recordings/file?id={e['id']}&part=meta", level="view")
        self.assertEqual(s, 200)
        return json.loads(data)

    def test_a_dab_station_is_recorded_as_itself(self):
        s, a = self.req("POST", "/api/decoders/sessions",
                        {"decoder": "dab", "freqHz": CENTRE, "params": {"block": "11D", "service": "C221"}})
        self.assertEqual(s, 201, a)
        self.assertTrue(self.wait(lambda: (lambda b: b and all(b[k] for k in ("label", "ensemble", "dls", "artist", "ptyName")))(
            self.radio.broadcast_station())))
        audio, iq = self.record("audio", "iq")

        # The audio: named, listed and described as the station.
        self.assertRegex(audio["id"], rf"^openhamshack-radio-{STAMP}-Shack-MP2-Tone-DAB$")
        self.assertEqual((audio["mode"], audio["freqHz"], audio["station"]), ("DAB", CENTRE, "GM4BRI"))
        self.assertEqual((audio["sampleRate"], audio["channels"]), (48_000, 2))
        side = self.sidecar(audio)
        self.assertEqual(side["kind"], "audio")                          # shack_rec's own, untouched
        self.assertEqual(side["broadcast"], {
            "kind": "dab", "mode": "DAB", "label": "Shack MP2 Tone", "shortLabel": "ShackMP2", "sid": "C221",
            "block": "11D", "freqHz": CENTRE, "ensemble": "Shack Test Mux", "eid": "C1CE", "ptyName": "Pop music",
            "dls": "Shack MP2 Tone - now: 1 kHz left, 1.5 kHz right", "title": "1 kHz left",
            "artist": "Shack MP2 Tone"})
        # What it said as it went: from the start, the station and its text.
        first = {k: v for c in side["changes"] if c["t"] < 0.5 for k, v in c.items() if k != "t"}
        self.assertEqual((first["mode"], first["label"], first["sid"], first["title"], first["artist"]),
                         ("DAB", "Shack MP2 Tone", "C221", "1 kHz left", "Shack MP2 Tone"))
        self.assertNotIn("FM", [c.get("mode") for c in side["changes"]])

        # Played by a client: FLAC at the station's rate and channels, with ranges.
        q = f"/api/recordings/file?id={audio['id']}&part=data"
        s, h, body = self.raw("GET", q, level="view")
        self.assertEqual((s, h["Content-Type"], h["Accept-Ranges"]), (200, "audio/flac", "bytes"))
        self.assertTrue(h["Content-Disposition"].startswith("inline"))
        self.assertTrue(body.startswith(b"fLaC"))
        path = Path(self.radio.recordings_dir(), audio["parts"]["data"]["name"])
        self.assertEqual(flac_rate_and_channels(path), (48_000, 2))
        s, h, part = self.raw("GET", q, headers={"Range": "bytes=0-41"}, level="view")
        self.assertEqual((s, h["Content-Range"], part), (206, f"bytes 0-41/{len(body)}", body[:42]))

        # The IQ: the whole block, named by it, and DAB rather than the mode from before.
        self.assertRegex(iq["id"], rf"^openhamshack-radio-{STAMP}-11D-222\.064MHz-DAB$")
        self.assertEqual((iq["mode"], iq["freqHz"]), ("DAB", CENTRE))
        g = sigmf.read_meta(Path(self.radio.recordings_dir(), iq["parts"]["data"]["name"]))["global"]
        self.assertEqual(g["openhamshack:receive"]["mode"], "dab")
        self.assertEqual(g["openhamshack:broadcast"]["label"], "Shack MP2 Tone")
        self.assertEqual(g["openhamshack:broadcast"]["eid"], "C1CE")
        self.assertTrue(g["core:description"].endswith("222.064000 MHz DAB, " + g["openhamshack:broadcast"]["label"]))

    def test_a_wide_fm_station_is_recorded_by_its_rds_name(self):
        s, a = self.req("POST", "/api/set", {"vfo": FM, "mode": "wfm"})
        self.assertEqual(s, 200, a)
        self.assertTrue(self.wait(lambda: (self.radio.state().get("rds") or {}).get("rt")))
        audio, iq = self.record("audio", "iq")
        self.assertRegex(audio["id"], rf"^openhamshack-radio-{STAMP}-SIM-ONE-WFM$")
        self.assertEqual((audio["mode"], audio["freqHz"], audio["channels"]), ("WFM", FM, 2))
        b = self.sidecar(audio)["broadcast"]
        self.assertEqual((b["kind"], b["mode"], b["label"], b["ps"], b["pi"], b["rt"], b["ptyName"], b["freqHz"]),
                         ("wfm", "WFM", "SIM ONE", "SIM ONE", "C201", "Sim One: 1 kHz left, 1.5 right", "Pop music",
                          FM))
        self.assertRegex(iq["id"], rf"^openhamshack-radio-{STAMP}-88\.600MHz-SIM-ONE-WFM$")
        self.assertEqual(iq["mode"], "WFM")

    def test_anything_else_is_named_by_the_dial_and_mode(self):
        audio, iq = self.record("audio", "iq", seconds=0.5)
        self.assertRegex(audio["id"], rf"^openhamshack-radio-{STAMP}-145\.500000MHz-FM$")
        self.assertRegex(iq["id"], rf"^openhamshack-radio-{STAMP}-145\.500MHz-FM$")
        self.assertEqual((audio["mode"], audio["channels"]), ("FM", 1))
        self.assertNotIn("broadcast", self.sidecar(audio))
        g = sigmf.read_meta(Path(self.radio.recordings_dir(), iq["parts"]["data"]["name"]))["global"]
        self.assertNotIn("openhamshack:broadcast", g)
        self.assertEqual(g["openhamshack:receive"]["mode"], "fm")


if __name__ == "__main__":
    unittest.main()
