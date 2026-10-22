"""PSKReporter spot upload (ohscore/pskreporter.py), against a socket on
this machine - nothing here may reach report.pskreporter.info.

The packets are read back with a small IPFIX parser written from the
developer page and RFC 5101 rather than from the module, so a field the
encoder puts in the wrong place, at the wrong length or under the wrong
template fails here instead of being silently dropped by the server."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import random
import socket
import struct
import tempfile
import time
import unittest

from ohscore import pskreporter
from ohscore.audio import NullAudio
from ohscore.pskreporter import Spotter


# ------------------------------------------------------------ IPFIX reader
def parse(data: bytes, templates: dict) -> dict:
    """{header fields, "records": [(template id, {field name: value})]}.
    `templates` carries what earlier packets defined, as a collector's
    would; template sets update it."""
    version, length, export, seq, domain = struct.unpack(">HHIII", data[:16])
    assert version == 10 and length == len(data), (version, length, len(data))
    out = {"export": export, "sequence": seq, "domain": domain, "records": [], "templates": False}
    pos = 16
    while pos < len(data):
        set_id, set_len = struct.unpack(">HH", data[pos:pos + 4])
        assert set_len % 4 == 0, f"set {set_id:#x} not padded to four bytes"
        body = data[pos + 4:pos + set_len]
        pos += set_len
        if set_id in (2, 3):
            out["templates"] = True
            tid, count = struct.unpack(">HH", body[:4])
            p = 4
            if set_id == 3:
                p += 2                      # scope field count
            fields = []
            for _ in range(count):
                el, flen = struct.unpack(">HH", body[p:p + 4])
                p += 4
                ent = None
                if el & 0x8000:
                    ent = struct.unpack(">I", body[p:p + 4])[0]
                    p += 4
                fields.append((el & 0x7FFF, flen, ent))
            templates[tid] = fields
            continue
        fields = templates[set_id]
        p = 0
        # Records follow one another until only padding is left.
        while p < len(body) and any(body[p:]):
            rec = {}
            for el, flen, ent in fields:
                if flen == 0xFFFF:
                    n = body[p]
                    p += 1
                    v = body[p:p + n].decode("utf-8")
                    p += n
                else:
                    raw = body[p:p + flen]
                    p += flen
                    v = int.from_bytes(raw, "big", signed=(el == 6 and ent == 30351))
                rec[NAMES.get((el, ent), el)] = v
            out["records"].append((set_id, rec))
    return out


NAMES = {(1, 30351): "senderCallsign", (2, 30351): "receiverCallsign", (3, 30351): "senderLocator",
         (4, 30351): "receiverLocator", (5, 30351): "frequency", (6, 30351): "sNR",
         (8, 30351): "decodingSoftware", (10, 30351): "mode", (11, 30351): "informationSource",
         (150, None): "flowStartSeconds"}


class Clock:
    def __init__(self, t=1_791_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def ft8(call, df=1200, snr=-7, grid="", dial=14_074_000.0, slot=1_791_000_000.0, **kw):
    ev = {"mode": "ft8", "slot": slot, "snr": snr, "dt": 0.1, "df": df, "text": f"CQ {call} {grid}".strip(),
          "call": call, "dial": dial}
    if grid:
        ev["grid"] = grid
    ev.update(kw)
    return ev


class Listener:
    def __init__(self, case):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(2.0)
        case.addCleanup(self.sock.close)
        self.addr = self.sock.getsockname()
        self.templates = {}

    def packet(self) -> dict:
        data, _ = self.sock.recvfrom(65536)
        return parse(data, self.templates)

    def nothing(self, wait=0.3) -> bool:
        self.sock.settimeout(wait)
        try:
            self.sock.recvfrom(65536)
            return False
        except socket.timeout:
            return True
        finally:
            self.sock.settimeout(2.0)


class Packets(unittest.TestCase):
    def setUp(self):
        self.rx = Listener(self)
        self.clock = Clock()
        self.sp = Spotter("OpenHamShack Radio 0.1.9", dest=self.rx.addr, clock=self.clock, rng=random.Random(1),
                          thread=False)
        self.addCleanup(self.sp.close)

    def test_a_packet_reads_back_with_every_field(self):
        self.assertTrue(self.sp.offer(ft8("G4ABC", df=1234, snr=-12, grid="IO91"), "M0XYZ", "IO86ha"))
        self.assertTrue(self.sp.offer(ft8("DL1AA", df=600, snr=5), "M0XYZ", "IO86ha"))
        self.clock.t += pskreporter.INTERVAL_S + pskreporter.JITTER_S
        self.assertEqual(self.sp.poll(), 1)
        pkt = self.rx.packet()
        self.assertTrue(pkt["templates"])
        self.assertEqual(pkt["export"], int(self.clock.t))
        recs = pkt["records"]
        rx = [r for tid, r in recs if tid == pskreporter.RX_TEMPLATE]
        self.assertEqual(rx, [{"receiverCallsign": "M0XYZ", "receiverLocator": "IO86ha",
                               "decodingSoftware": "OpenHamShack Radio 0.1.9"}])
        tx = [r for tid, r in recs if tid == pskreporter.TX_TEMPLATE]
        self.assertEqual(tx[0], {"senderCallsign": "G4ABC", "frequency": 14_075_234, "sNR": -12, "mode": "FT8",
                                 "senderLocator": "IO91", "informationSource": 1,
                                 "flowStartSeconds": 1_791_000_000})
        self.assertEqual(tx[1]["senderCallsign"], "DL1AA")
        self.assertEqual(tx[1]["senderLocator"], "")
        self.assertEqual(tx[1]["sNR"], 5)

    def test_qo100_downlink_needs_the_fifth_frequency_byte(self):
        # 10.489 GHz does not fit the four bytes the developer page shows;
        # the template says five, and the value must come back whole.
        self.sp.offer(ft8("DL2BB", df=1500, dial=10_489_540_000.0), "M0XYZ", "IO86")
        self.clock.t += 1000
        self.sp.poll()
        tx = [r for tid, r in self.rx.packet()["records"] if tid == pskreporter.TX_TEMPLATE]
        self.assertEqual(tx[0]["frequency"], 10_489_541_500)

    def test_q65_ft4_and_js8_are_spots_and_other_events_are_not(self):
        me, loc = "M0XYZ", "IO86"
        self.assertTrue(self.sp.offer(ft8("G1AAA", mode="ft4"), me, loc))
        self.assertTrue(self.sp.offer(ft8("G1AAB", mode="q65"), me, loc))
        self.assertTrue(self.sp.offer(ft8("G1AAC", mode="js8"), me, loc))
        for ev in (ft8("G1AAD", mode="psk31"),                 # no callsign field in that mode's decodes
                   ft8("<...>"),                               # a hash the decoder could not resolve
                   ft8("G1AAE", lowConfidence=True),           # WSJT-X's "?" a-priori decode
                   ft8("M0XYZ"),                               # ourselves
                   {"mode": "ft8", "snr": -3, "df": 100, "text": "TNX 73 GL", "dial": 14_074_000.0},
                   {"mode": "ft8", "slot": 0, "error": "jt9 crashed"}):
            self.assertFalse(self.sp.offer(ev, me, loc), ev)
        self.clock.t += 1000
        self.sp.poll()
        modes = {r["senderCallsign"]: r["mode"] for tid, r in self.rx.packet()["records"]
                 if tid == pskreporter.TX_TEMPLATE}
        self.assertEqual(modes, {"G1AAA": "FT4", "G1AAB": "Q65", "G1AAC": "JS8"})

    def test_nothing_without_a_callsign_and_locator(self):
        self.assertFalse(self.sp.offer(ft8("G4ABC"), "", "IO86"))
        self.assertFalse(self.sp.offer(ft8("G4ABC"), "M0XYZ", ""))
        self.assertFalse(self.sp.offer(ft8("G4ABC"), "M0XYZ", "IO8"))
        self.clock.t += 1000
        self.assertEqual(self.sp.poll(), 0)


class Timing(unittest.TestCase):
    def setUp(self):
        self.rx = Listener(self)
        self.clock = Clock()
        self.sp = Spotter("OpenHamShack QO-100 NB 0.1.9", dest=self.rx.addr, clock=self.clock, rng=random.Random(2),
                          thread=False)
        self.addCleanup(self.sp.close)

    def test_one_packet_per_five_minutes_off_the_clock(self):
        t0 = self.clock.t
        self.sp.offer(ft8("G4ABC"), "M0XYZ", "IO86")
        due = self.sp.next_send
        self.assertGreaterEqual(due - t0, pskreporter.INTERVAL_S)
        self.assertLessEqual(due - t0, pskreporter.INTERVAL_S + pskreporter.JITTER_S)
        for dt, call in ((1, "G1AAA"), (60, "G2BBB"), (200, "G3CCC"), (pskreporter.INTERVAL_S - 1, "G4DDD")):
            self.clock.t = t0 + dt
            self.assertTrue(self.sp.offer(ft8(call), "M0XYZ", "IO86"))
            self.assertEqual(self.sp.poll(), 0, f"sent after {dt} s")
        self.assertTrue(self.rx.nothing())
        self.clock.t = due
        self.assertEqual(self.sp.poll(), 1)
        self.assertEqual(len([r for tid, r in self.rx.packet()["records"] if tid == pskreporter.TX_TEMPLATE]), 5)
        # A spot straight after waits a whole interval again.
        self.sp.offer(ft8("DL9ZZ"), "M0XYZ", "IO86")
        self.clock.t = due + 10
        self.assertEqual(self.sp.poll(), 0)
        self.clock.t = due + pskreporter.INTERVAL_S + pskreporter.JITTER_S
        self.assertEqual(self.sp.poll(), 1)

    def test_same_call_and_band_once_per_window(self):
        me, loc = "M0XYZ", "IO86"
        self.assertTrue(self.sp.offer(ft8("G4ABC", df=1000), me, loc))
        self.clock.t += 15
        self.assertFalse(self.sp.offer(ft8("G4ABC", df=1800), me, loc))           # same band, next slot
        self.assertTrue(self.sp.offer(ft8("G4ABC", dial=7_074_000.0), me, loc))  # another band
        self.clock.t += pskreporter.DEDUPE_S
        self.assertTrue(self.sp.offer(ft8("G4ABC"), me, loc))                    # the window has passed
        self.assertEqual(len(self.sp.pending), 3)

    def test_a_full_packet_goes_early_and_the_rest_follows(self):
        n = 120
        for i in range(n):
            self.sp.offer(ft8(f"G{i:03d}AB", df=100 + i), "M0XYZ", "IO86")
        self.assertGreater(self.sp.poll(), 1)
        got, sizes = 0, []
        # Read every datagram the poll sent.
        self.rx.sock.settimeout(0.5)
        while True:
            try:
                data, _ = self.rx.sock.recvfrom(65536)
            except socket.timeout:
                break
            sizes.append(len(data))
            got += len([r for tid, r in parse(data, self.rx.templates)["records"]
                        if tid == pskreporter.TX_TEMPLATE])
        self.assertEqual(got, n)
        self.assertTrue(all(s <= pskreporter.MAX_PACKET for s in sizes), sizes)

    def test_templates_in_the_first_three_packets_then_hourly(self):
        seen = []
        for i in range(5):
            self.sp.offer(ft8(f"G{i}ABC"), "M0XYZ", "IO86")
            self.clock.t += 400
            self.sp.poll()
            seen.append(self.rx.packet()["templates"])
        self.assertEqual(seen, [True, True, True, False, False])
        self.clock.t += pskreporter.TEMPLATE_EVERY_S
        self.sp.offer(ft8("G9ABC"), "M0XYZ", "IO86")
        self.clock.t += 400
        self.sp.poll()
        self.assertTrue(self.rx.packet()["templates"])

    def test_sequence_counts_data_records(self):
        self.sp.offer(ft8("G1ABC"), "M0XYZ", "IO86")
        self.sp.offer(ft8("G2ABC"), "M0XYZ", "IO86")
        self.clock.t += 400
        self.sp.poll()
        first = self.rx.packet()
        self.sp.offer(ft8("G3ABC"), "M0XYZ", "IO86")
        self.clock.t += 400
        self.sp.poll()
        second = self.rx.packet()
        self.assertEqual(first["sequence"], 0)
        self.assertEqual(second["sequence"], 3)       # one receiver and two sender records before it
        self.assertEqual(first["domain"], second["domain"])

    def test_a_network_failure_is_quiet_and_costs_only_that_batch(self):
        dead = Spotter("x", dest=("127.0.0.1", 9), clock=self.clock, sock=Broken(), thread=False)
        dead.offer(ft8("G4ABC"), "M0XYZ", "IO86")
        self.clock.t += 1000
        with self.assertLogs("ohscore.pskreporter", "WARNING") as logs:
            self.assertEqual(dead.poll(), 0)
        self.assertEqual(len(logs.output), 1)
        dead.offer(ft8("G5ABC"), "M0XYZ", "IO86")
        self.clock.t += 1000
        with self.assertLogs("ohscore.pskreporter", "DEBUG") as logs:
            dead.poll()
        self.assertTrue(all("DEBUG" in line for line in logs.output), logs.output)   # once an hour, not every time

    def test_turning_off_drops_the_batch(self):
        self.sp.offer(ft8("G4ABC"), "M0XYZ", "IO86")
        self.sp.clear()
        self.clock.t += 1000
        self.assertEqual(self.sp.poll(), 0)
        self.assertTrue(self.rx.nothing())


class Broken:
    def sendto(self, data, dest):
        raise OSError("Network is unreachable")

    def close(self):
        pass


class EngineHook(unittest.TestCase):
    """The setting through a real app's engine: off sends nothing, on needs
    a station, and a decode event becomes a spot at the downlink."""

    def setUp(self):
        from ohsnb.radio import Radio
        self.rx = Listener(self)
        os.environ["OHS_PSKREPORTER"] = "%s:%d" % self.rx.addr
        self.addCleanup(os.environ.__setitem__, "OHS_PSKREPORTER", "127.0.0.1:9")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.r = Radio({"device": "sim", "audioBackend": "null"}, persist=False, data_dir=self.tmp.name,
                       audio=NullAudio(realtime=False))
        self.addCleanup(lambda: self.r.spotter and self.r.spotter.close())

    def test_off_by_default_sends_nothing_and_makes_no_spotter(self):
        self.assertFalse(self.r.state()["pskReporter"])
        self.r.set(callsign="M0XYZ", locator="IO86")
        self.r._emit_event(ft8("G4ABC", dial=10_489_540_000.0))
        self.assertIsNone(self.r.spotter)
        self.r.flush_spots()
        self.assertTrue(self.rx.nothing())

    def test_refused_without_callsign_and_locator(self):
        with self.assertRaisesRegex(ValueError, "callsign and locator"):
            self.r.set(pskReporter=True)
        with self.assertRaisesRegex(ValueError, "callsign and locator"):
            self.r.set(pskReporter=True, callsign="M0XYZ", locator="nowhere")
        self.assertFalse(self.r.state()["pskReporter"])
        self.r.set(pskReporter=True, callsign="M0XYZ", locator="IO86")
        self.assertTrue(self.r.state()["pskReporter"])

    def test_a_decode_is_spotted_at_the_downlink_heard(self):
        self.r.set(pskReporter=True, callsign="M0XYZ", locator="IO86ha")
        dial = self.r.state()["rxDial"]
        self.assertGreater(dial, 10_489_000_000.0)          # NB's dial is the downlink
        ev = ft8("G4ABC", df=1500)
        del ev["dial"]                                        # the engine adds the dial, as it does for decoders
        self.r._emit_event(ev)
        self.assertEqual(self.r.spotter.dest, self.rx.addr)
        self.assertTrue(self.r.spotter.software.startswith("OpenHamShack QO-100 NB "))
        self.r.flush_spots()
        tx = [r for tid, r in self.rx.packet()["records"] if tid == pskreporter.TX_TEMPLATE]
        self.assertEqual(tx[0]["senderCallsign"], "G4ABC")
        self.assertEqual(tx[0]["frequency"], round(dial + 1500))

    def test_turning_it_off_drops_what_was_waiting(self):
        self.r.set(pskReporter=True, callsign="M0XYZ", locator="IO86")
        self.r._emit_event(ft8("G4ABC"))
        self.r.set(pskReporter=False)
        self.r.spotter.flush()
        self.assertTrue(self.rx.nothing())


if __name__ == "__main__":
    unittest.main()
