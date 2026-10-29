"""Radiosondes on a map (29/10/2026): Radio's sonde receive, its table, its
SondeHub upload and its routes.

auto_rx's programs are not on a test machine, and no sonde recording here
is clearly free to redistribute (auto_rx's own test samples come from
rfhead.net with no licence stated), so the decoders are the simulator's
stand-ins (ohsradio/devices/simsonde.py): real processes started with
auto_rx's command lines, fed the channel Radio cuts from the receiver's IQ
as 16-bit IQ, answering in each decoder's own JSON form. The simulated
air carries a sonde's carrier for the scan to find. So everything Radio
itself does is exercised for real; only the decoding inside the programs
is stood in for. Checked over the HTTP API:

- **The scan finds it and locks on**, the dial on the sonde, and the
  sonde is listed in the TV contract's exact shape, with its track and
  (by serial) its profile.
- **The session** ends with the last client, its lease, or its presence,
  the dial, mode and repeater offset put back.
- **Decoder lines** as auto_rx's handle_decoder_line and telemetry_filter
  take them, for each kind's own spelling of type and serial.
- **A whole flight**: ascent, burst seen, descent, landed where it came
  down; predictions marked as such.
- **Kept on disk**: 24 hours, 7 days once landed, across a restart.
- **SondeHub**: the upload's shape at a local stand-in for SondeHub, the
  station placed only at its locator's centre; nothing sent with the
  setting off, offline, or from the simulator; nothing said to the
  operator about being offline. Launch sites and Tawhiri likewise.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import gzip
import http.client
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import numpy as np

from ohscore import sdr
from ohscore.engine import ReceiverHeld, TxRefused
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio import sonde as sondemod
from ohsradio import sondehub
from ohsradio.devices import simsonde
from ohsradio.radio import Radio

from listen_helpers import ListeningSim, make_listener
from test_server import SECRET

HOME = 145_500_000.0
CONTRACT = {"serial", "type", "freqHz", "lat", "lon", "altM", "climbMs", "headingDeg", "speedKmh", "tempC",
            "humidity", "pressureHpa", "batteryV", "frame", "lastHeard", "phase", "burst", "landing", "track"}
IO75RL = (55.4792, -4.5417)          # 55 deg 28.75' N, 4 deg 32.5' W: the subsquare's centre


def wait(cond, timeout=60.0, radio=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if radio is not None:
            radio.heartbeat()
        if cond():
            return True
        time.sleep(0.05)
    return False


def cfg_for(**over):
    return {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
            "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
            "locator": "IO75RL", **over}


def stamp(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FakeSondeHub:
    """SondeHub's API as far as Radio uses it, on a local port: it keeps
    every request (method, path, headers, body decoded) and answers /sites
    and /tawhiri with what a test gives it."""

    def __init__(self, sites=None, tawhiri=None):
        self.got = []
        self.sites = sites or {}
        self.tawhiri = tawhiri
        hub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _body(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw) if raw else None

            def do_PUT(self):
                hub.got.append(("PUT", self.path, dict(self.headers), self._body()))
                self._answer(200, b"")

            def do_GET(self):
                hub.got.append(("GET", self.path, dict(self.headers), None))
                if self.path.startswith("/sites"):
                    # gzip whether asked or not, as SondeHub's gateway does.
                    self._answer(200, gzip.compress(json.dumps(hub.sites).encode()), gz=True)
                elif self.path.startswith("/tawhiri") and hub.tawhiri is not None:
                    self._answer(200, json.dumps(hub.tawhiri).encode())
                else:
                    self._answer(404, b"{}")

            def _answer(self, code, body, gz=False):
                self.send_response(code)
                if gz:
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def puts(self, path):
        return [g for g in self.got if g[0] == "PUT" and g[1] == path]


def closed_port() -> str:
    """A URL nothing answers at: Radio offline, as far as it can tell."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


class Served:
    """A Radio on the simulator with a sonde on 403.5 MHz, behind the HTTP
    server, the simulator's stand-ins for auto_rx's programs."""

    def __init__(self, test, data_dir, air=True, launch_ago=1200.0, **over):
        cfg = cfg_for(**over)
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=data_dir, audio=self.audio,
                           device=ListeningSim(dict(cfg), 2_400_000.0, [simsonde.SondeAir()] if air else []))
        self.radio.sonde.programs = simsonde.Programs(launch=time.time() - launch_ago)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        test.assertEqual(self.srv.start_radio(), "")

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

    def sondes(self):
        s, a = self.req("GET", "/api/sonde/sondes", level="view")
        assert s == 200, a
        return a

    def shutdown(self):
        self.srv.shutdown()


# -- the scan's own arithmetic ---------------------------------------------------
class TheScan(unittest.TestCase):
    def test_the_hops_cover_400_to_406_and_the_second_pass_covers_the_first_ones_spikes(self):
        for fs in (2_400_000.0, 2_048_000.0, 1_000_000.0, 240_000.0):
            half = sondemod.USABLE * fs - sondemod.EDGE_HZ
            for f in np.arange(400.0e6, 406.0e6, 5_000.0):
                ok = [any(sondemod.DC_GUARD_HZ <= abs(f - c) <= half for c in sondemod.hops(fs, shifted))
                      for shifted in (False, True)]
                self.assertTrue(any(ok), (fs, f))

    def test_a_carrier_is_found_on_its_10_khz_channel_and_the_spike_is_not(self):
        fs, centre, n = 2_400_000.0, 403_000_000.0, 3000
        freqs = centre + np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
        rng = np.random.default_rng(1)
        # A spectrum averaged over a hundred FFTs, as a hop's is: the noise's
        # spread is a fraction of a dB, not a single FFT's exponential.
        power = rng.gamma(100.0, 1 / 100.0, n)
        for f0, db in ((403_512_000.0, 30.0), (402_400_000.0, 15.0)):
            # A sonde's two tones either side of its channel, 800 Hz bins.
            for tone in (f0 - 2400.0, f0 + 2400.0):
                power[np.argmin(np.abs(freqs - tone))] += 10 ** (db / 10)
        power[n // 2] += 1e6                                 # the receiver's DC spike
        found = sondemod.find_peaks(power, freqs, centre, fs)
        self.assertEqual([f for f, _s in found], [403_510_000.0, 402_400_000.0])
        self.assertGreater(found[0][1], found[1][1])
        self.assertEqual(sondemod.find_peaks(power, freqs, centre, fs, lambda f: f == 403_510_000.0)[0][0],
                         402_400_000.0)

    def test_dft_detect_answers_read_as_auto_rx_reads_them(self):
        # As auto_rx v1.9.0's dft_detect prints them (its RS41 and M20
        # recordings gave the first and third).
        self.assertEqual(sondemod.parse_detect("RS41: 0.9888 , -230.7Hz\n"), ("RS41", -230.7))
        self.assertEqual(sondemod.parse_detect("DFM9: 0.9801 , -49.1Hz\n"), ("DFM", -49.1))
        self.assertEqual(sondemod.parse_detect("M20: -0.9762 , +921.5Hz\n"), ("M20", 921.5))
        self.assertEqual(sondemod.parse_detect("MEISEI: -0.91 , +10.0Hz"), (None, 10.0))
        self.assertEqual(sondemod.parse_detect("RS92: 0.95"), ("RS92", 0.0))
        self.assertEqual(sondemod.parse_detect(""), (None, 0.0))

    def test_the_channel_comes_out_at_the_decoders_rate_with_the_sonde_at_dc(self):
        fs, off = 2_400_000.0, -50_000.0 + 1_000.0
        for rate in (48_000, 50_000):
            d = sondemod.Ddc(fs, -50_000.0, rate)
            t = np.arange(int(fs)) / fs
            x = np.exp(2j * np.pi * off * t).astype(np.complex64)
            y = np.concatenate([d(x[a:a + 24_000]) for a in range(0, len(x), 24_000)])
            self.assertAlmostEqual(len(y), rate, delta=rate * 0.01)
            spec = np.abs(np.fft.fft(y[rate // 4:])) ** 2
            peak = np.fft.fftfreq(len(spec), 1 / rate)[np.argmax(spec)]
            self.assertAlmostEqual(peak, 1_000.0, delta=10.0)
            iq = np.frombuffer(sondemod.Cs16()(y), "<i2")
            self.assertLess(np.abs(iq).max(), 2_000)        # iq_dec's 16 bits never wrap (Cs16)


# -- a decoder's lines ---------------------------------------------------------------
def rs41_line(now, **over):
    doc = {"type": "RS41", "frame": 4321, "id": "W1234567", "datetime": stamp(now), "lat": 55.61, "lon": -4.21,
           "alt": 12345.6, "vel_h": 12.5, "heading": 80.0, "vel_v": 5.1, "sats": 9, "bt": 65535, "batt": 2.7,
           "temp": -40.5, "humidity": 30.2, "pressure": 190.1, "subtype": "RS41-SGP", "version": "1.9.0"}
    doc.update(over)
    return doc


class DecoderLines(unittest.TestCase):
    """Lines in each decoder's own JSON form (its printf in auto_rx's
    demod/mod/*.c), with made-up values."""

    def test_an_rs41(self):
        now = time.time()
        rd = sondemod.reading(rs41_line(now), "RS41", 403_500_000.0, now)
        self.assertEqual((rd["serial"], rd["type"], rd["shType"], rd["shSubtype"], rd["manufacturer"]),
                         ("W1234567", "RS41-SGP", "RS41", "RS41-SGP", "Vaisala"))
        self.assertEqual((rd["lat"], rd["lon"], rd["altM"], rd["climbMs"], rd["speedKmh"], rd["headingDeg"]),
                         (55.61, -4.21, 12345.6, 5.1, 45.0, 80.0))
        self.assertEqual((rd["tempC"], rd["humidity"], rd["pressureHpa"], rd["batteryV"], rd["frame"]),
                         (-40.5, 30.2, 190.1, 2.7, 4321))

    def test_each_kind_spells_its_type_and_serial_as_auto_rx_reads_them(self):
        now = time.time()
        base = {"datetime": stamp(now), "lat": 55.6, "lon": -4.2, "alt": 1000.0, "version": "1.9.0"}
        cases = [
            ("DFM", {"type": "DFM", "frame": 300, "id": "DFM-21012345", "subtype": "0xD:DFM17"},
             ("21012345", "DFM17", "DFM", "DFM17", "Graw")),
            ("DFM", {"type": "DFM", "frame": 300, "id": "DFM-21012345", "subtype": "0x7"},
             ("21012345", "DFM", "DFM", "DFM", "Graw")),
            ("M10", {"type": "M20", "frame": 10, "id": "M20-911-2-00269"},
             ("911-2-00269", "M20", "M20", None, "Meteomodem")),
            ("LMS6", {"type": "LMS", "frame": 10, "id": "LMS6-123456", "subtype": "LMS6X"},
             ("123456", "LMS6-403", "LMS6-403", "LMS6X", "Lockheed Martin")),
            ("MEISEI", {"type": "IMS100", "frame": 10, "id": "IMS100-12345", "subtype": "IMS100"},
             ("12345", "iMS-100", "iMS-100", None, "Meisei")),
        ]
        for kind, doc, want in cases:
            rd = sondemod.reading({**base, **doc}, kind, 403e6, now)
            self.assertIsNotNone(rd, doc)
            self.assertEqual((rd["serial"], rd["type"], rd["shType"], rd["shSubtype"], rd["manufacturer"]), want)

    def test_lines_auto_rx_would_not_take(self):
        now = time.time()
        bad = [rs41_line(now, version="1.8.2"),                 # another build's decoder
               {k: v for k, v in rs41_line(now).items() if k != "alt"},
               rs41_line(now, lat=0.0, lon=0.0),                # no GPS lock
               rs41_line(now, sats=3),
               rs41_line(now, alt=52_000.0),                    # above max_altitude
               rs41_line(now - 4 * 3600),                       # more than 3 hours out
               rs41_line(now, id="ABC"),                        # not a Vaisala serial
               {**rs41_line(now), "type": "DFM", "id": "DFM-xxxxxxxx", "subtype": "0xD:DFM17"}]
        for i, doc in enumerate(bad):
            kind = "DFM" if doc["type"] == "DFM" else "RS41"
            self.assertIsNone(sondemod.reading(doc, kind, 403e6, now), i)

    def test_a_time_of_day_alone_is_put_on_the_nearest_day(self):
        now = datetime(2026, 10, 30, 0, 5, tzinfo=timezone.utc).timestamp()
        self.assertEqual(sondemod.parse_datetime("23:59:30Z", now),
                         datetime(2026, 10, 29, 23, 59, 30, tzinfo=timezone.utc).timestamp())
        self.assertEqual(sondemod.parse_datetime("00:04:00.5Z", now),
                         datetime(2026, 10, 30, 0, 4, 0, 500000, tzinfo=timezone.utc).timestamp())

    def test_an_encrypted_rs41_is_listed_but_never_placed_or_uploaded(self):
        now = time.time()
        rd = sondemod.reading(rs41_line(now, lat=0.0, lon=0.0, alt=0.0, encrypted=True, subtype="RS41-SGM"),
                              "RS41", 403e6, now)
        self.assertEqual((rd["serial"], rd["type"], rd["lat"], rd["encrypted"]),
                         ("W1234567", "RS41-SGM-Encrypted", None, True))
        hub = sondehub.SondeHub(None, lambda: True, lambda: True, lambda: ("GM4BRI", "IO75RL"))
        hub.add(rd)
        self.assertEqual(len(hub.queue), 0)


# -- a whole flight ------------------------------------------------------------------
class AFlight(unittest.TestCase):
    def fly(self, table, launch, until, every=10.0):
        out = []
        for ft in np.arange(0.0, until, every):
            now = launch + ft
            line = json.loads(simsonde._line({"serial": "Z0000001", "kind": "RS41"}, int(ft), float(ft), launch))
            rd = sondemod.reading(line, "RS41", 403.5e6, now)
            out.append(table.heard(rd, now))
        return out

    def test_ascent_burst_descent_and_landing(self):
        table = sondemod.SondeTable(None)
        launch = time.time() - 4 * 3600
        seen = self.fly(table, launch, simsonde.T_UP + 4000.0)
        phases = [v["phase"] for v in seen]
        self.assertEqual(phases[0], "ascent")
        first = {p: phases.index(p) for p in ("descent", "landed")}
        self.assertTrue(set(phases[:first["descent"]]) == {"ascent"})
        self.assertTrue(set(phases[first["descent"]:first["landed"]]) == {"descent"})
        self.assertEqual(set(phases[first["landed"]:]), {"landed"})
        v = seen[-1]
        top = simsonde.flight(simsonde.T_UP)
        self.assertEqual(v["burst"]["predicted"], False)
        self.assertAlmostEqual(v["burst"]["altM"], top["alt"], delta=60.0)
        self.assertAlmostEqual(v["burst"]["lat"], top["lat"], delta=0.01)
        down = simsonde.flight(1e9)
        self.assertEqual((v["landing"]["lat"], v["landing"]["lon"]), (down["lat"], down["lon"]))
        one = table.sonde("Z0000001")
        self.assertEqual(one["track"][0]["altM"], 20.0)
        self.assertEqual(one["track"][-1]["lat"], down["lat"])
        prof = one["profile"]
        self.assertEqual(set(prof[0]), {"altM", "tempC", "humidity", "pressureHpa", "windKmh", "windDirDeg"})
        self.assertGreaterEqual(max(p["altM"] for p in prof), 29_900)
        self.assertEqual(prof[0]["windDirDeg"], 250.0)           # blowing towards 070 is a wind from 250
        self.assertEqual(prof[10]["windKmh"], round(simsonde._wind(prof[10]["altM"]) * 3.6, 1))

    def test_predictions_are_marked_and_a_seen_burst_is_not_replaced(self):
        table = sondemod.SondeTable(None)
        launch = time.time() - 4 * 3600
        self.fly(table, launch, 3000.0)
        v = table.get("Z0000001")
        est = sondemod.ballistic(v, launch + 3000.0, 26_000.0, 5.0)
        self.assertEqual(est["burst"]["predicted"], True)
        self.assertEqual(est["burst"]["altM"], 26_000)
        self.assertGreater(est["landing"]["lon"], v["lon"])     # drifting east, as the wind blows
        changed = table.predicted("Z0000001", est)
        self.assertEqual((changed["burst"], changed["landing"]), (est["burst"], est["landing"]))
        # Into the descent: the burst seen stands whatever is predicted.
        table2 = sondemod.SondeTable(None)
        self.fly(table2, launch, simsonde.T_UP + 600.0)
        seen = table2.get("Z0000001")["burst"]
        self.assertEqual(seen["predicted"], False)
        table2.predicted("Z0000001", {"burst": {"lat": 1.0, "lon": 1.0, "altM": 1, "predicted": True},
                                      "landing": {"lat": 2.0, "lon": 2.0, "utc": "x"}})
        self.assertEqual(table2.get("Z0000001")["burst"], seen)
        self.assertEqual(table2.get("Z0000001")["landing"]["lat"], 2.0)

    def test_tawhiris_answer_is_read_as_burst_and_landing(self):
        # The shape SondeHub's Tawhiri answers with (asked 29/10/2026),
        # longitudes 0-360.
        doc = {"metadata": {}, "request": {}, "warnings": {}, "prediction": [
            {"stage": "ascent", "trajectory": [
                {"altitude": 20.0, "datetime": "2026-10-29T12:00:00Z", "latitude": 55.48, "longitude": 355.46},
                {"altitude": 29998.9, "datetime": "2026-10-29T13:39:55Z", "latitude": 55.5329,
                 "longitude": 356.2180}]},
            {"stage": "descent", "trajectory": [
                {"altitude": 29998.9, "datetime": "2026-10-29T13:39:55Z", "latitude": 55.5329, "longitude": 356.2180},
                {"altitude": 255.8, "datetime": "2026-10-29T14:25:00Z", "latitude": 55.5539,
                 "longitude": 356.5920}]}]}
        got = sondehub.parse_tawhiri(doc)
        self.assertEqual(got["burst"], {"lat": 55.5329, "lon": -3.782, "altM": 29999, "predicted": True})
        self.assertEqual(got["landing"], {"lat": 55.5539, "lon": -3.408, "utc": "2026-10-29T14:25:00Z"})
        self.assertIsNone(sondehub.parse_tawhiri({"error": {"type": "RequestException"}}))


# -- the session, over the API --------------------------------------------------------
class OverTheApi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.box = Served(self, self.dir)
        self.addCleanup(lambda: self.box and self.box.shutdown())

    def test_the_scan_finds_the_sonde_and_decodes_it_and_the_dial_goes_back(self):
        box = self.box
        s, a = box.req("POST", "/api/sonde/session?client=tv-1")
        self.assertEqual((s, a["state"]), (200, "scanning"), a)
        self.assertTrue(wait(lambda: box.radio.sonde.state == "tracking" and box.radio.sonde.counts["frames"] >= 3,
                             radio=box.radio), box.radio.sonde.view())
        want_tr = {"kind": "RS41", "freqHz": simsonde.FREQ_HZ, "serial": "Z0000001"}
        self.assertTrue(wait(lambda: box.radio.state()["sonde"]["tracking"] == want_tr, 10, radio=box.radio))
        st = box.radio.state()
        self.assertEqual((st["rxOwner"]["by"], st["vfo"]), ("sonde", simsonde.FREQ_HZ))
        a = box.sondes()
        self.assertEqual(set(a), {"state", "freqHz", "sondehub", "sondes"})
        self.assertEqual((a["state"], a["freqHz"]), ("tracking", simsonde.FREQ_HZ))
        self.assertEqual(set(a["sondehub"]), {"enabled", "lastUploadUtc", "error"})
        (v,) = a["sondes"]
        self.assertEqual(set(v), CONTRACT)
        want = simsonde.flight(1200.0)
        self.assertEqual((v["serial"], v["type"], v["phase"], v["freqHz"]),
                         ("Z0000001", "RS41-SGP", "ascent", simsonde.FREQ_HZ))
        self.assertAlmostEqual(v["altM"], want["alt"], delta=500.0)
        self.assertEqual(set(v["track"][0]), {"t", "lat", "lon", "altM"})
        self.assertEqual(v["burst"]["predicted"], True)
        s, one = box.req("GET", "/api/sonde/sondes/Z0000001", level="view")
        self.assertEqual(s, 200)
        self.assertEqual(set(one), CONTRACT | {"profile"})
        self.assertEqual(box.req("GET", "/api/sonde/sondes/X9999999", level="view")[0], 404)
        # Another holder, a tune or a key-up is refused while it holds.
        with self.assertRaises(ReceiverHeld):
            box.radio.set(vfo=HOME)
        s, a = box.req("DELETE", "/api/sonde/session?client=tv-1")
        self.assertEqual(s, 200)
        self.assertTrue(wait(lambda: box.radio.state()["sonde"]["state"] == "idle", 10, radio=box.radio))
        st = box.radio.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"], st["rptOffsetHz"]), ({}, HOME, "fm", 600_000.0))
        self.assertEqual(box.sondes()["state"], "idle")
        self.assertEqual(len(box.sondes()["sondes"]), 1)            # kept after the session

    def test_the_simulators_frames_are_never_uploaded(self):
        box = self.box
        box.radio.sonde.join("tv-1")
        self.assertTrue(wait(lambda: box.radio.sonde.counts["frames"] >= 2, radio=box.radio))
        self.assertEqual(len(box.radio.sonde.hub.queue), 0)

    def test_kept_across_a_restart(self):
        box = self.box
        box.radio.sonde.join("tv-1")
        self.assertTrue(wait(lambda: box.radio.sonde.counts["frames"] >= 2, radio=box.radio))
        box.radio.sonde.end("stopped")
        before = box.sondes()["sondes"]
        box.shutdown()
        box.radio.stop()
        self.box = Served(self, self.dir, air=False)
        after = self.box.sondes()["sondes"]
        self.assertEqual([(v["serial"], v["lat"], v["frame"]) for v in after],
                         [(v["serial"], v["lat"], v["frame"]) for v in before])
        self.assertEqual(len(after[0]["track"]), len(before[0]["track"]))


class Retention(unittest.TestCase):
    def test_a_day_and_a_week_once_landed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        now = time.time()
        path = Path(tmp.name) / "sonde" / "sondes.json"
        path.parent.mkdir(parents=True)

        def entry(serial, age, phase):
            return {"serial": serial, "type": "RS41-SG", "phase": phase, "lat": 55.5, "lon": -4.0, "altM": 100.0,
                    "lastHeardTs": now - age, "lastHeard": sondemod._iso(now - age), "burst": None,
                    "landing": None, "maxAlt": None, "descentRun": 0, "landedRun": 0, "landedFrames": 0}
        sondes = [entry("W0000001", 2 * 3600, "ascent"), entry("W0000002", 25 * 3600, "descent"),
                  entry("W0000003", 3 * 86400, "landed"), entry("W0000004", 8 * 86400, "landed")]
        path.write_text(json.dumps({"schema": 1, "rev": 9, "sondes": sondes,
                                    "tracks": {s["serial"]: [[now - 9e5, 55.5, -4.0, 100.0]] for s in sondes},
                                    "profiles": {}}))
        table = sondemod.SondeTable(path)
        self.assertEqual(sorted(v["serial"] for v in table.view()), ["W0000001", "W0000003"])
        # And the loss of the expired ones is itself kept.
        table.save(force=True)
        self.assertEqual(sorted(v["serial"] for v in sondemod.SondeTable(path).view()), ["W0000001", "W0000003"])
        with mock.patch.object(sondemod.time, "time", return_value=now + 86400):
            self.assertEqual(table.expire(time.time()), ["W0000001"])


# -- the session's ends, as AIS's -------------------------------------------------------
class TheSession(unittest.TestCase):
    def radio(self, **over):
        r, audio, dev = make_listener([], **cfg_for(**over))
        self.addCleanup(r._tmp.cleanup)
        self.addCleanup(r.stop)
        r.start()
        return r

    def test_a_client_that_stops_renewing_lets_it_go(self):
        r = self.radio(mode="usb", vfo=144_300_000.0)
        with mock.patch.object(sondemod, "CLIENT_LEASE_S", 0.3):
            r.sonde.join("tv-1")
            self.assertEqual(r.state()["rxOwner"]["by"], "sonde")
            self.assertTrue(400e6 <= r.state()["vfo"] <= 406e6)
            self.assertTrue(wait(lambda: r.sonde.state == "idle", 10, radio=r))
        st = r.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"], r.sonde.why), ({}, 144_300_000.0, "usb", "idle"))

    def test_the_last_client_leaving_gives_the_receiver_back_at_once(self):
        r = self.radio()
        centre_before = r.centre
        r.sonde.join("tv-1")
        r.sonde.join("phone-2")
        r.sonde.leave("tv-1")
        r.sonde.tick()
        self.assertEqual(r.sonde.state, "scanning")
        r.sonde.leave("phone-2")
        self.assertTrue(wait(lambda: r.sonde.state == "idle", 10, radio=r))
        st = r.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"], st["rptOffsetHz"]), ({}, HOME, "fm", 600_000.0))
        self.assertTrue(wait(lambda: r.centre == centre_before, 10, radio=r), (r.centre, centre_before))

    def test_tuning_and_keying_are_refused_while_it_holds(self):
        r = self.radio(receive_only=False)
        r.sonde.join("tv-1")
        with self.assertRaises(ReceiverHeld) as e:
            r.set(vfo=HOME)
        self.assertIn("radiosondes", str(e.exception))
        with self.assertRaises(TxRefused):
            r.ptt(True)
        self.assertFalse(r.state()["keyed"])
        r.sonde.end("stopped")
        self.assertEqual(r.state()["rxOwner"], {})

    def test_refusals_when_it_cannot_start(self):
        from ohscore.decoders import Refused
        r = self.radio()
        with self.assertRaises(Refused) as e:
            r.sonde.join("")
        self.assertEqual(e.exception.code, "bad_client")
        with tempfile.TemporaryDirectory() as empty:
            r.sonde.programs = sondemod.Programs(empty)       # an install without auto_rx's programs
            with self.assertRaises(Refused) as e:
                r.sonde.join("tv-1")
            self.assertEqual(e.exception.code, "decoder_unavailable")
        r.sonde.programs = simsonde.Programs()
        r.stop()
        with self.assertRaises(Refused) as e:
            r.sonde.join("tv-1")
        self.assertEqual(e.exception.code, "not_running")

    def test_the_radio_stopping_ends_it(self):
        r = self.radio()
        r.sonde.join("tv-1")
        r.stop()
        self.assertEqual((r.sonde.state, r.sonde.why), ("idle", "radio_stopped"))
        self.assertEqual((r.state()["vfo"], r.state()["mode"]), (HOME, "fm"))


try:
    from test_ham_presence import Base as PresenceBase
except Exception:  # noqa: BLE001 - its own imports need shack_sdr; skipped below without it
    PresenceBase = unittest.TestCase


@unittest.skipUnless(sdr.available() and PresenceBase is not unittest.TestCase, "no shack_sdr wheel for this machine")
class WithPresence(PresenceBase):
    def test_goodbye_ends_the_sonde_map_at_once(self):
        self.following()
        self.fake.arrive("tv-lounge", ["sonde"])
        s, a = self.req("POST", "/api/sonde/session?client=tv-lounge")
        self.assertEqual((s, a["state"]), (200, "scanning"), a)
        self.assertEqual(self.radio.state()["rxOwner"]["by"], "sonde")
        self.fake.push("gone", {"client": "tv-lounge", "why": "goodbye"})
        self.assertTrue(wait(lambda: self.radio.sonde.state == "idle", 5))
        st = self.radio.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"]), ({}, 145_500_000.0, "fm"))

    def test_presence_renews_the_map_for_a_present_client(self):
        self.following()
        self.fake.arrive("tv-lounge", ["sonde"])
        self.assertTrue(wait(lambda: self.status()["presence"]["clients"] == ["tv-lounge"]))
        with mock.patch.object(sondemod, "CLIENT_LEASE_S", 0.3):
            self.req("POST", "/api/sonde/session?client=tv-lounge")
            self.req("POST", "/api/sonde/session", {"client": "old-tv"})
            self.assertTrue(wait(lambda: self.radio.sonde.view()["clients"] == 1, 5))
            time.sleep(1.0)
            self.assertEqual((self.radio.sonde.state != "idle", list(self.radio.sonde.clients)),
                             (True, ["tv-lounge"]))


# -- SondeHub ----------------------------------------------------------------------------
class TheUpload(unittest.TestCase):
    def hub(self, locator="IO75RL", upload=True, online=True, base=None):
        self.on = {"upload": upload, "online": online}
        h = sondehub.SondeHub(None, lambda: self.on["upload"], lambda: self.on["online"],
                              lambda: ("gm4bri", locator), base_url=base or self.fake.base)
        return h

    def setUp(self):
        self.fake = FakeSondeHub()
        self.addCleanup(self.fake.close)

    def frames(self, hub, n=3):
        now = time.time()
        for i in range(n):
            hub.add(sondemod.reading(rs41_line(now + i, frame=4321 + i), "RS41", 403_500_000.0, now + i))

    def test_the_upload_is_auto_rxs_and_places_the_station_only_at_its_locators_centre(self):
        # An 8-character locator, a few hundred metres across: still only
        # the 6-character square's centre goes out.
        hub = self.hub(locator="IO75RL37")
        self.frames(hub)
        self.assertTrue(hub.flush())
        (put,) = self.fake.puts("/sondes/telemetry")
        _m, _p, headers, batch = put
        self.assertEqual(headers["Content-Encoding"], "gzip")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertTrue(headers["User-Agent"].startswith("OpenHamShack-Radio/"))
        self.assertEqual(len(batch), 3)
        t = batch[0]
        self.assertEqual(t["uploader_position"], [IO75RL[0], IO75RL[1], 0.0])
        self.assertNotEqual(t["uploader_position"][:2], [round(x, 4) for x in sondehub.locator_position("IO75RL37")])
        self.assertEqual((t["uploader_callsign"], t["software_name"]), ("GM4BRI", "OpenHamShack-Radio"))
        self.assertEqual({k: t[k] for k in ("manufacturer", "type", "subtype", "serial", "frame", "lat", "lon", "alt",
                                            "temp", "humidity", "pressure", "vel_v", "vel_h", "heading", "sats",
                                            "batt", "burst_timer", "frequency")},
                         {"manufacturer": "Vaisala", "type": "RS41", "subtype": "RS41-SGP", "serial": "W1234567",
                          "frame": 4321, "lat": 55.61, "lon": -4.21, "alt": 12345.6, "temp": -40.5, "humidity": 30.2,
                          "pressure": 190.1, "vel_v": 5.1, "vel_h": 12.5, "heading": 80.0, "sats": 9, "batt": 2.7,
                          "burst_timer": 65535, "frequency": 403.5})
        for k in ("datetime", "time_received"):
            datetime.strptime(t[k], "%Y-%m-%dT%H:%M:%S.%fZ")
        # And the station on SondeHub's map: the same centre, nothing nearer.
        (listener,) = self.fake.puts("/listeners")
        self.assertEqual(listener[3]["uploader_position"], [IO75RL[0], IO75RL[1], 0.0])
        self.assertEqual(hub.view()["error"], None)
        self.assertIsNotNone(hub.view()["lastUploadUtc"])

    def test_the_locators_centre(self):
        self.assertEqual(sondehub.station_position("IO75RL"), IO75RL)
        self.assertEqual(sondehub.station_position("io75rl"), IO75RL)
        self.assertEqual(sondehub.station_position("IO75RL37"), IO75RL)
        self.assertEqual(sondehub.station_position("IO75"), (55.5, -5.0))
        self.assertIsNone(sondehub.station_position(""))

    def test_switched_off_nothing_is_sent_and_nothing_said(self):
        hub = self.hub(upload=False)
        self.frames(hub)
        self.assertTrue(hub.flush())
        self.on["upload"] = True
        self.assertTrue(hub.flush())                      # nothing was kept to send later
        self.assertEqual(self.fake.got, [])
        self.on["upload"] = False
        self.assertEqual(hub.view(), {"enabled": False, "lastUploadUtc": None, "error": None})

    def test_offline_it_is_a_silent_no_op(self):
        hub = self.hub(base=closed_port())
        self.frames(hub)
        self.assertFalse(hub.flush())
        self.assertEqual(hub.view(), {"enabled": True, "lastUploadUtc": None, "error": None})
        self.assertEqual(len(hub.queue), 0)                # dropped, not piled up
        hub.predict("W1234567", {"launch_latitude": 55.0})
        hub.step(time.time() + 100)                        # Tawhiri unreachable: no answer, no error
        self.assertIsNone(hub.prediction("W1234567"))
        self.assertFalse(hub.refresh_sites())
        self.assertEqual(hub.launches(*IO75RL), [])

    def test_no_callsign_says_so(self):
        hub = self.hub(locator="")
        self.frames(hub)
        self.assertFalse(hub.flush())
        self.assertIn("callsign and locator", hub.view()["error"])
        self.assertEqual(self.fake.got, [])

    def test_offline_over_the_api_nothing_reaches_the_operator(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        box = Served(self, tmp.name, air=False)
        self.addCleanup(box.shutdown)
        hub = box.radio.sonde.hub
        hub.base_url = closed_port()
        hub.add(sondemod.reading(rs41_line(time.time()), "RS41", 403.5e6, time.time()))
        hub.step(time.time() + 3600)
        a = box.sondes()
        self.assertEqual(a["sondehub"], {"enabled": True, "lastUploadUtc": None, "error": None})
        self.assertEqual(box.req("GET", "/api/sonde/launches", level="view"), (200, []))


class LaunchesAndPredictions(unittest.TestCase):
    SITES = {
        "03918": {"station": "03918", "station_name": "Castor Bay (United Kingdom)",
                  "position": [-6.3431, 54.5030], "alt": 18, "ascent_rate": 4.8, "burst_altitude": 30300,
                  "descent_rate": 3, "times": ["0:00:00", "12:00:00"], "rs_types": [["41", "403.4"]]},
        "-81": {"station": "-81", "station_name": "A firing range", "position": [-3.4167, 54.3201], "alt": 7,
                "rs_types": ["13"], "times": []},
        "98753": {"station": "98753", "station_name": "Far away", "position": [125.65, 7.13], "times": ["0:00:00"]},
    }

    def setUp(self):
        self.fake = FakeSondeHub(sites=self.SITES)
        self.addCleanup(self.fake.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.online = [True]

    def hub(self):
        return sondehub.SondeHub(self.folder, lambda: True, lambda: self.online[0], lambda: ("GM4BRI", "IO75RL"),
                                 base_url=self.fake.base)

    def test_upcoming_launches_near_the_station_from_the_kept_site_list(self):
        hub = self.hub()
        self.assertEqual(hub.launches(*IO75RL), [])           # nothing fetched yet
        self.assertTrue(hub.sites_wanted)
        now = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc).timestamp()
        hub.step(now)                                          # the thread's turn fetches it
        got = hub.launches(*IO75RL, now=now)
        self.assertEqual([(v["site"], v["utc"]) for v in got],
                         [("03918", "2026-10-29T12:00:00Z"), ("03918", "2026-10-30T00:00:00Z")])
        v = got[0]
        self.assertEqual((v["name"], v["types"], v["freqHz"], v["burstAltM"]),
                         ("Castor Bay (United Kingdom)", ["RS41"], 403_400_000, 30300))
        self.assertAlmostEqual(v["distanceKm"], 158, delta=1)            # Castor Bay from IO75RL's centre
        self.assertEqual(self.fake.got[0][2]["User-Agent"].split("/")[0], "OpenHamShack-Radio")
        # Kept: a restart offline still lists them; with the setting off, nothing.
        self.fake.close()
        again = self.hub()
        self.assertEqual(len(again.launches(*IO75RL, now=now)), 2)
        self.online[0] = False
        self.assertEqual(again.launches(*IO75RL, now=now), [])

    def test_tawhiri_answers_replace_the_ballistic_estimate_once_they_come(self):
        self.fake.tawhiri = {"prediction": [
            {"stage": "ascent", "trajectory": [{"altitude": 30300.0, "datetime": "x", "latitude": 55.6,
                                                "longitude": 356.0}]},
            {"stage": "descent", "trajectory": [{"altitude": 10.0, "datetime": "2026-10-29T14:00:00Z",
                                                 "latitude": 55.7, "longitude": 357.0}]}]}
        r, audio, dev = make_listener([], **cfg_for())
        self.addCleanup(r._tmp.cleanup)
        svc = r.sonde
        svc.hub.base_url = self.fake.base
        now = time.time()
        svc._line("RS41", 403.5e6, json.dumps(rs41_line(now)))
        v = svc.table.get("W1234567")
        self.assertEqual(v["burst"]["predicted"], True)                  # the ballistic estimate first
        self.assertEqual(v["burst"]["altM"], 26_000)
        self.assertEqual([g for g in self.fake.got if g[1].startswith("/tawhiri")], [])
        svc.hub.step(time.time())
        (ask,) = [g for g in self.fake.got if g[1].startswith("/tawhiri")]
        self.assertIn("launch_longitude=355.79", ask[1])                 # 0-360, as Tawhiri wants
        self.assertIn("ascent_rate=5.1", ask[1])
        svc.predicted_at.clear()
        svc._line("RS41", 403.5e6, json.dumps(rs41_line(now + 1, frame=4322)))
        v = svc.table.get("W1234567")
        self.assertEqual(v["burst"], {"lat": 55.6, "lon": -4.0, "altM": 30300, "predicted": True})
        self.assertEqual(v["landing"], {"lat": 55.7, "lon": -3.0, "utc": "2026-10-29T14:00:00Z"})


if __name__ == "__main__":
    unittest.main()
