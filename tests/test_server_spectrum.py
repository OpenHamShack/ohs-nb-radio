"""spectrum/1 and overlay/1 (CLIENT-UI-PLAN.md §2, §3; docs/SERVER-API.md
"spectrum/1") over real WebSockets on loopback: per-client crop,
decimation, peak or mean and 8 or 16 bits, the caps, latest-wins with its
gap flag, the eight-client budget, and the overlay's items from Radio's own
band plan, local frequencies, station lists and dial.

The rows a test checks come from a fake engine: known bins published into
the engine's own `wide` feed of a Radio that is not running, so each
column can be worked out by hand. One test runs NB's real simulator for
the rows the engine itself makes. Receive only: nothing here keys."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import base64
import http.client
import json
import os
import queue
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from ohscore import shacklibs
from ohscore.dsp.spectrum import Line
from ohscore.server import shack, spectrum
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.radio import Radio
from test_server import SECRET, ServerTest

sp = shacklibs.spectrum()
# The real home, not the scratch one scratch_home moved HOME to.
SCHEMAS = Path(os.environ.get("OHSTEST_REAL_HOME", str(Path.home()))) / "ohs-libs" / "spec" / "schemas"

START, BIN, NBINS = 144_000_000.0, 1000.0, 2000      # 144.000-146.000 MHz


def validator(name):
    import jsonschema
    from referencing import Registry, Resource
    schemas = [json.loads(p.read_text()) for p in SCHEMAS.glob("*.schema.json")]
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas if "$id" in s])
    return jsonschema.Draft202012Validator(json.loads((SCHEMAS / name).read_text()), registry=reg)


def bins(spike_at=500, seed=1):
    """Noise around -120 dB with one carrier at -80 dB, inside the levels
    window (floor about -131, top 60 dB above): which column the carrier
    lands in, and how high, is known."""
    db = -120.0 + np.random.default_rng(seed).normal(0, 1.0, NBINS)
    db[spike_at] = -80.0
    return db


class Client:
    """A WebSocket client: frames read on a thread of its own into a queue,
    unless `hold` (then nothing is read and the server's socket fills)."""

    def __init__(self, port, path="/api/spectrum/v1", rcvbuf=None, read=True):
        s = socket.socket()
        if rcvbuf:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        s.settimeout(10)
        s.connect(("127.0.0.1", port))
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET {path} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                   f"{shack.SHACK_SECRET_HEADER}: {SECRET}\r\nX-OpenHamShack-User: brian\r\n"
                   f"X-OpenHamShack-Level: view\r\nX-OpenHamShack-Device: dev_TEST\r\n\r\n").encode())
        self.s, self.f = s, s.makefile("rb")
        self.status = self.f.readline()
        while self.f.readline() not in (b"\r\n", b""):
            pass
        self.q: queue.Queue = queue.Queue()
        self.go = threading.Event()
        if read:
            self.go.set()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                self.go.wait()
                b0, b1 = self.f.read(2)
                n = b1 & 0x7F
                if n == 126:
                    n = struct.unpack("!H", self.f.read(2))[0]
                elif n == 127:
                    n = struct.unpack("!Q", self.f.read(8))[0]
                data = self.f.read(n)
                op = b0 & 0x0F
                self.q.put(("close", data) if op == 0x8 else
                           ("text", json.loads(data)) if op == 0x1 else ("row", sp.decode(data)))
                if op == 0x8:
                    return
        except (OSError, ValueError):
            self.q.put(("gone", None))

    def send(self, msg):
        data = json.dumps(msg).encode()
        mask = os.urandom(4)
        head = struct.pack("!BB", 0x81, 0x80 | len(data)) if len(data) < 126 else \
            struct.pack("!BBH", 0x81, 0x80 | 126, len(data))
        self.s.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def subscribe(self, **kw):
        self.send({"type": "subscribe", "stream": "main", **kw})

    def next(self, want, timeout=5.0, pump=None):
        """The next message satisfying want(kind, msg), calling pump()
        while waiting (a fake engine's next row); None after timeout."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pump is not None:
                pump()
            try:
                kind, msg = self.q.get(timeout=0.03)
            except queue.Empty:
                continue
            if want(kind, msg):
                return msg
        return None

    def close(self):
        # shutdown first: the reader's makefile keeps the socket open
        # through close() alone, and the server would never see it go.
        try:
            self.s.shutdown(socket.SHUT_RDWR)
            self.s.close()
        except OSError:
            pass


class RadioSpectrum(unittest.TestCase):
    """Radio, not running, with rows put into its wide feed by hand."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "callsign": "GM4BRI",
               "licenceClass": "full", "locator": "IO75TU", "localRadiusKm": 50}
        audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), audio, secret=SECRET)
        self.port = self.srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.t = 1_800_000_000.0
        self.db = bins()

    def client(self, **kw):
        c = Client(self.port, **kw)
        self.addCleanup(c.close)
        self.assertIn(b"101", c.status)
        return c

    def publish(self, db=None, step=0.05, kind="wide"):
        self.t += step
        self.radio._publish(kind, Line((self.t, START, BIN, self.db if db is None else db)))

    def row(self, c, timeout=5.0):
        return c.next(lambda k, m: k == "row", timeout, pump=self.publish)

    def req(self, method, path, body=None, level="view"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
                   "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
                   "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        out = r.status, json.loads(r.read())
        c.close()
        return out

    # ------------------------------------------------------------ rows
    def test_a_row_is_this_clients_crop_and_columns_of_the_shared_feed(self):
        c = self.client()
        c.subscribe(cols=100, loHz=144_400_000, hiHz=144_600_000, reduce="peak")
        r = self.row(c)
        self.assertIsNotNone(r)
        # 200 bins of 1 kHz cropped, 100 columns of two bins each.
        self.assertEqual((len(r.values), r.depth, r.stream), (100, 8, 0))
        self.assertEqual((r.lo_hz, r.col_hz), (144_400_000.0, 2000.0))
        # Bin 500 (144.500 MHz) is column 50: the carrier; the noise sits
        # about 10 dB over the floor.
        self.assertEqual(int(np.argmax(r.values)), 50)
        win = self.srv.spectrum.streams["main"]["window"]
        step = win.step(8)
        self.assertAlmostEqual(win.floor + r.values[50] * step, -80.0, delta=step)
        self.assertAlmostEqual(np.median(r.values) * step, 10.0, delta=3.0)
        self.assertFalse(r.gap)

    def test_peak_keeps_a_carrier_that_mean_averages_down(self):
        c = self.client()
        c.subscribe(cols=10, reduce="peak")
        peak = self.row(c)
        c.subscribe(cols=10, reduce="mean")
        mean = c.next(lambda k, m: k == "row" and m.col_hz == peak.col_hz and m.values[2] != peak.values[2],
                      pump=self.publish)
        self.assertIsNotNone(mean)
        # 200 bins a column: bin 500 is in column 2. Its peak is the
        # carrier; its mean is the power average of the 200 bins, which
        # the carrier lifts only some 17 dB over the noise.
        win = self.srv.spectrum.streams["main"]["window"]
        step = win.step(8)
        power = 10 * np.log10(np.mean(10 ** (self.db[400:600] / 10)))
        self.assertAlmostEqual(win.floor + peak.values[2] * step, -80.0, delta=step)
        self.assertAlmostEqual(win.floor + mean.values[2] * step, power, delta=step)
        self.assertLess(power, -95.0)

    def test_depth_16_with_its_own_levels_step(self):
        c = self.client()
        c.subscribe(cols=64, depth=16)
        levels = c.next(lambda k, m: k == "text" and m["type"] == "levels", pump=self.publish)
        r = self.row(c)
        self.assertEqual((r.depth, r.values.dtype), (16, np.uint16))
        win = self.srv.spectrum.streams["main"]["window"]
        self.assertAlmostEqual(levels["dbStep"], (win.top - win.floor) / 65536)
        self.assertEqual(levels["dbFloor"], win.floor)
        self.assertTrue(r.levels_changed)       # the first row after the window this client was given

    def test_cols_and_fps_beyond_the_caps_are_clamped(self):
        c = self.client()
        wide = np.concatenate([self.db, self.db, self.db])      # 6000 bins
        c.subscribe(cols=100_000, fps=1000)
        first = c.next(lambda k, m: k == "row", pump=lambda: self.publish(wide))
        self.assertEqual(len(first.values), spectrum.MAX_COLS)
        # Two seconds of capture time at 100 rows a second: 25 a second go.
        while not c.q.empty():
            c.q.get()
        for _ in range(200):
            self.publish(wide, step=0.01)
            time.sleep(0.01)
        time.sleep(0.5)
        ts = [m.t_ms for k, m in list(c.q.queue) if k == "row"]
        # Never closer than the cap's 40 ms (less 10 % slack for jitter),
        # yet nearly every one of those 50 slots filled.
        self.assertGreaterEqual(min(np.diff(ts)), 36, ts)
        self.assertGreaterEqual(len(ts), 40)

    def test_a_stalled_client_gets_the_newest_row_and_a_gap(self):
        c = self.client(rcvbuf=4096, read=False)
        c.subscribe(cols=2048, depth=16)
        big = np.concatenate([self.db, self.db])
        # 4 kB rows into a client that reads nothing: the socket fills, and
        # from then on each row replaces the one waiting.
        for _ in range(400):
            self.publish(big)
            time.sleep(0.005)
        c.go.set()
        rows = []
        while True:
            r = c.next(lambda k, m: k == "row", timeout=1.0)
            if r is None:
                break
            rows.append(r)
        self.assertGreater(len(rows), 1)
        gaps = [r for r in rows if r.gap]
        self.assertTrue(gaps, [r.seq for r in rows])
        # A dropped row also shows as a jump in seq (stamped when offered).
        seqs = [r.seq for r in rows]
        self.assertTrue(any(b - a > 1 for a, b in zip(seqs, seqs[1:])), seqs)
        # And the last row sent is the newest the engine made.
        self.assertEqual(rows[-1].t_ms, int(self.t * 1000))

    def test_nothing_is_sent_for_a_stream_nobody_subscribed(self):
        c = self.client()
        desc = c.next(lambda k, m: k == "text" and m["type"] == "stream", pump=self.publish)
        self.assertEqual((desc["stream"], desc["srcBins"], desc["binHz"], desc["loHz"]), ("main", NBINS, BIN, START))
        self.assertIsNone(c.next(lambda k, m: k == "row", timeout=0.5, pump=self.publish))

    def test_messages_are_valid_spectrum_1(self):
        if not SCHEMAS.is_dir():
            self.skipTest("ohs-libs' schemas are not checked out here")
        v = validator("spectrum.schema.json")
        c = self.client()
        c.subscribe(cols=64)
        seen = {}
        c.next(lambda k, m: k == "text" and seen.setdefault(m["type"], m) and {"stream", "levels"} <= set(seen),
               pump=self.publish)
        c.send({"type": "subscribe", "stream": "pan-1", "cols": 10})
        c.send({"type": "subscribe", "stream": "main", "cols": 10, "depth": 12})
        errs = [c.next(lambda k, m: k == "text" and m["type"] == "error", pump=self.publish) for _ in range(2)]
        self.assertEqual([e["code"] for e in errs], ["unknown_stream", "bad_subscribe"])
        for m in (seen["stream"], seen["levels"], *errs):
            v.validate(m)
        # Refusals leave the socket and its subscription as they were.
        self.assertIsNotNone(self.row(c))

    def test_the_ninth_client_is_refused_busy(self):
        clients = [self.client() for _ in range(spectrum.MAX_CLIENTS)]
        for c in clients:
            c.subscribe(cols=16)
        self.assertTrue(all(self.row(c) is not None for c in clients))
        ninth = self.client()
        err = ninth.next(lambda k, m: k == "text")
        self.assertEqual((err["type"], err["code"]), ("error", "busy"))
        self.assertIsNotNone(ninth.next(lambda k, m: k == "close"))
        # One goes, and there is room again.
        clients[0].close()
        end = time.monotonic() + 5
        while time.monotonic() < end and self.srv.spectrum.clients >= spectrum.MAX_CLIENTS:
            self.publish()          # the loop finds the client gone on its next write or read
            time.sleep(0.02)
        again = self.client()
        again.subscribe(cols=16)
        self.assertIsNotNone(self.row(again))

    def test_api_events_wide_is_unchanged_beside_it(self):
        ev = self.client(path="/api/events?kinds=wide")
        c = self.client()
        c.subscribe(cols=16)
        self.assertIsNotNone(self.row(c))
        old = ev.next(lambda k, m: k == "text" and m["kind"] == "wide", pump=self.publish)
        self.assertEqual((old["startHz"], old["binHz"], old["n"]), (START, BIN, NBINS))
        cdb = np.frombuffer(base64.b64decode(old["cdb"]), "<i2")
        self.assertEqual(int(cdb[500]), -8000)

    # ------------------------------------------------------------ overlay
    def overlay(self, c, op="snapshot"):
        return c.next(lambda k, m: k == "text" and m["type"] == "overlay" and m["op"] == op, pump=self.publish)

    def test_the_overlay_on_the_socket_is_radios_plan_channels_stations_and_dial(self):
        s, mine = self.req("POST", "/api/local-frequencies/mine",
                           {"name": "GB3GA", "freqHz": 145_712_500, "mode": "fm", "category": "repeater"}, "control")
        self.assertEqual(s, 201, mine)
        scan = self.radio.bandscan
        scan.records["dab"]["ensembles"] = [{"block": "12B", "freqHz": 145_000_000, "label": "Test Mux",
                                             "services": [{"sid": "C221", "label": "Shack One"}]}]
        c = self.client()
        c.subscribe(cols=200, loHz=144_000_000, hiHz=146_000_000)
        snap = self.overlay(c)
        self.assertIsNotNone(snap)
        if SCHEMAS.is_dir():
            validator("overlay.schema.json").validate(snap)
        by = {i["id"]: i for i in snap["items"]}
        # The band: the plan in force for GM4BRI (RSGB's), as shack_bandplan has it.
        cw = [i for i in snap["items"] if i["layer"] == "band" and i["loHz"] == 144_025_000]
        self.assertEqual([(i["label"], i["hiHz"], i["role"], i["readAtHzPerPx"]) for i in cw],
                         [("CW", 144_100_000, "segment.cw", None)])
        self.assertTrue(any(i["role"] == "segment.beacon" for i in snap["items"]))
        # The operator's own frequency, tuned by its first action.
        ch = by["lf:mine:" + mine["id"]]
        self.assertEqual((ch["kind"], ch["layer"], ch["label"], ch["role"]),
                         ("channel", "channels", "GB3GA", "channel.repeater"))
        self.assertEqual(ch["actions"][0], {"id": "tune", "label": "Tune", "do": "post", "path": "api/set",
                                            "body": {"changes": {"vfo": 145_712_500, "mode": "fm"}},
                                            "level": "control"})
        # The DAB list's ensemble (as the band scan keeps it), played by its service.
        dab = by["dab:12B"]
        self.assertEqual((dab["kind"], dab["label"], dab["actions"][0]["body"]["params"]),
                         ("station", "Test Mux", {"block": "12B", "service": "C221"}))
        # The dial, and an upsert when it moves.
        self.assertEqual(by["dial"]["loHz"], self.radio.state()["vfo"])
        s, a = self.req("POST", "/api/set", {"vfo": 145_600_000.0}, "control")
        self.assertEqual(s, 200, a)
        up = c.next(lambda k, m: k == "text" and m["type"] == "overlay" and m["op"] == "upsert"
                    and any(i["id"] == "dial" for i in m["items"]), pump=self.publish)
        self.assertIsNotNone(up)
        self.assertGreater(up["rev"], snap["rev"])
        self.assertEqual(next(i for i in up["items"] if i["id"] == "dial")["loHz"], 145_600_000.0)
        self.assertFalse(any(a.get("level") == "transmit" for i in snap["items"] for a in i.get("actions", [])))

    def test_the_overlay_over_http_and_its_half_span_margin(self):
        ids = {}
        for name, f in (("in", 145_100_000), ("margin", 145_290_000), ("out", 145_350_000)):
            s, e = self.req("POST", "/api/local-frequencies/mine", {"name": name, "freqHz": f, "mode": "fm"},
                            "control")
            ids[name] = "lf:mine:" + e["id"]
        # A view of 145.0-145.2 MHz: 100 kHz either side is sent as well.
        s, a = self.req("GET", "/api/overlay/v1?loHz=145000000&hiHz=145200000")
        self.assertEqual(s, 200, a)
        self.assertEqual((a["type"], a["op"]), ("overlay", "snapshot"))
        if SCHEMAS.is_dir():
            validator("overlay.schema.json").validate(a)
        got = {i["id"] for i in a["items"]}
        self.assertLessEqual({ids["in"], ids["margin"]}, got)
        self.assertNotIn(ids["out"], got)
        # The NCDXF beacons are the beacons layer, not channels.
        s, a = self.req("GET", "/api/overlay/v1?loHz=14000000&hiHz=14350000")
        b = [i for i in a["items"] if i["id"] == "lf:ncdxf:20m:14100000"]
        self.assertEqual([(i["kind"], i["layer"]) for i in b], [("beacon", "beacons")])
        # A radio that has never run has no span to default to.
        for q in ("", "?loHz=2&hiHz=1", "?loHz=x&hiHz=1"):
            s, a = self.req("GET", "/api/overlay/v1" + q)
            self.assertEqual((s, a["code"]), (400, "bad_range"), q)


class EngineRows(ServerTest):
    """NB's real engine on the simulator: rows of its own wide scope."""

    def test_rows_of_the_real_wide_scope(self):
        c = Client(self.port)
        self.addCleanup(c.close)
        c.subscribe(cols=300, depth=8)
        desc = c.next(lambda k, m: k == "text" and m["type"] == "stream" and m["stream"] == "main", timeout=20)
        self.assertIsNotNone(desc)
        r = c.next(lambda k, m: k == "row" and m.stream == 0, timeout=20)
        self.assertIsNotNone(r)
        self.assertEqual(len(r.values), min(300, desc["srcBins"]))
        self.assertAlmostEqual(r.lo_hz, desc["loHz"], delta=desc["binHz"])
        self.assertGreater(int(r.values.max()), 0)


if __name__ == "__main__":
    unittest.main()
